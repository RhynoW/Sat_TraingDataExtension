#!/usr/bin/env python3
"""
ml_bigru_labeler.py — 小型雙向 GRU「物理殘差序列標註器」原型（Model 3 / 序列版）
=============================================================================
定位（與既有兩套模型互補）：
  Model 1 (監督式 LGBM, 逐窗特徵)：Starlink LEO 內強，OOD 誤報 → 需物理閘門。
  Model 2 (IsolationForest, 逐轉換物理殘差)：regime-agnostic、無監督、無時序記憶。
  Model 3 (本檔, 雙向 GRU)：吃「物理殘差序列」，逐時步輸出機動機率——
    以雙向時序脈絡（前後鄰居）壓抑孤立雜訊尖峰、辨識「持續段」，
    理論上比逐點 IsolationForest 更能抓連續機動、少誤報單點跳動。

輸入通道（與 Model 2 完全相同的 4 條物理殘差；皆已扣除自然演化）：
  z_drag  = NRLMSIS 阻力殘差 Δa / 0.10 km
  z_di    = Δinclination / 0.005 deg
  z_de    = Δecc / 2e-4
  z_draan = J2 修正後 ΔRAAN 殘差 / 0.03 deg

標籤：MEME 真值 transitions_full（medium+large 嚴重度）逐時步標記（±tol 內為正）。
切分：依衛星分組 80/20；FORMOSAT-3A(29052) 永遠留作 OOD holdout（期望 flag≈0）。

用法： python ml_bigru_labeler.py --max-sats 120 --epochs 40
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

import torch
import torch.nn as nn

from ml_model2_anomaly import physical_residuals, _load, _collapse, _CH
from atmospheric_drag import load_space_weather
from compare_tle_vs_ephemeris import load_registry

FORMOSAT_OOD = 29052
DAY_NS = int(24 * 3.6e12)


# ────────────────────────────────────────────────────────────────────────────
# 資料：逐衛星物理殘差序列 + 逐時步標籤
# ────────────────────────────────────────────────────────────────────────────

def build_truth(data_root: Path, gap_h: float = 48.0):
    """回傳 (ep_by, tr_by)：
      ep_by = {sat: [(start_ns,end_ns)]}  collapse 後 episode（**僅供 eval 逐-episode 配對**）
      tr_by = {sat: np.array(transition_ns)}  medium+large 逐轉換原始 t_to（**供訓練緊標籤**）
    分離兩者，避免 ±tol 膨脹把頻繁機動的 Starlink 整段標成正 → 退化成 base-rate。"""
    tg = sorted((data_root / "meme_truth").glob("transitions_full_*.csv"))
    truth = pd.read_csv(tg[-1])
    truth = truth[truth["da_severity"].isin(["medium", "large"])].copy()
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True)
    gap = int(gap_h * 3.6e12)
    ep_by = {s: _collapse(g["t_to"].astype("int64").to_numpy(), gap)
             for s, g in truth.groupby("sat_name")}
    tr_by = {s: np.sort(g["t_to"].astype("int64").to_numpy())
             for s, g in truth.groupby("sat_name")}
    return ep_by, tr_by


def label_epochs_tight(epoch_ns: np.ndarray, tran_ns: np.ndarray, tol_ns: int) -> np.ndarray:
    """訓練緊標籤：僅在「最接近某 medium/large 轉換 t_to（±tol，一個 TLE 節拍）」的
    epoch 標 1；不做 episode 膨脹 → 正樣本稀疏、逼模型真正判別（非 base-rate）。"""
    y = np.zeros(len(epoch_ns), np.float32)
    if len(tran_ns) == 0:
        return y
    for tn in tran_ns:
        j = int(np.argmin(np.abs(epoch_ns - tn)))
        if abs(epoch_ns[j] - tn) <= tol_ns:
            y[j] = 1.0
    return y


def load_sequences(con, sats, sw, tr_by, train_tol_ns, channels):
    """逐衛星 → (name, nid, epoch_ns[T], X[T,C], y_tight[T])。"""
    seqs = []
    for name, nid in sats:
        r = physical_residuals(_load(con, nid), sw)
        if r.empty or len(r) < 8:
            continue
        X = np.clip(np.nan_to_num(r[channels].to_numpy(np.float32)), -200, 200)
        ep_ns = r["epoch"].astype("int64").to_numpy()
        y = label_epochs_tight(ep_ns, tr_by.get(name, np.array([])), train_tol_ns)
        seqs.append((name, int(nid), ep_ns, X, y))
    return seqs


# ────────────────────────────────────────────────────────────────────────────
# 模型
# ────────────────────────────────────────────────────────────────────────────

class BiGRULabeler(nn.Module):
    def __init__(self, n_ch=4, hidden=64, layers=2, dropout=0.2):
        super().__init__()
        self.gru = nn.GRU(n_ch, hidden, num_layers=layers, batch_first=True,
                          bidirectional=True, dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Sequential(
            nn.Linear(2 * hidden, hidden), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden, 1),
        )

    def forward(self, x):                      # x:[B,L,4]
        h, _ = self.gru(x)                     # [B,L,2H]
        return self.head(h).squeeze(-1)        # [B,L] logits


def make_windows(seqs, L=48, stride=8):
    """訓練用固定長度滑窗（逐時步標籤）。短序列整段 pad。"""
    Xw, Yw, Mw = [], [], []
    for (_, _, _, X, y) in seqs:
        T = len(X)
        if T <= L:
            pad = L - T
            Xw.append(np.pad(X, ((0, pad), (0, 0))))
            Yw.append(np.pad(y, (0, pad)))
            Mw.append(np.pad(np.ones(T, np.float32), (0, pad)))
        else:
            for s in range(0, T - L + 1, stride):
                Xw.append(X[s:s + L]); Yw.append(y[s:s + L])
                Mw.append(np.ones(L, np.float32))
            # 尾段補一個貼齊尾巴的窗
            if (T - L) % stride != 0:
                Xw.append(X[T - L:]); Yw.append(y[T - L:])
                Mw.append(np.ones(L, np.float32))
    return (np.asarray(Xw, np.float32), np.asarray(Yw, np.float32),
            np.asarray(Mw, np.float32))


# ────────────────────────────────────────────────────────────────────────────
# 訓練 / 推論
# ────────────────────────────────────────────────────────────────────────────

def train(model, Xtr, Ytr, Mtr, dev, epochs=40, bs=64, lr=2e-3):
    scale = torch.tensor([5.0], device=dev)  # 殘差已物理地板正規化，再 /5 收斂較穩
    Xt = torch.tensor(Xtr, device=dev) / scale
    Yt = torch.tensor(Ytr, device=dev)
    Mt = torch.tensor(Mtr, device=dev)
    pos = float(Yt[Mt > 0].sum()); neg = float((Mt > 0).sum()) - pos
    pw = torch.tensor([max(1.0, neg / max(1.0, pos))], device=dev)
    print(f"  訓練窗={len(Xt)} pos_rate={pos/max(1.0,pos+neg):.4f} pos_weight={pw.item():.1f}")
    lossf = nn.BCEWithLogitsLoss(weight=None, pos_weight=pw, reduction="none")
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    n = len(Xt)
    for ep in range(epochs):
        model.train(); perm = torch.randperm(n, device=dev); tot = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            logit = model(Xt[idx])
            l = lossf(logit, Yt[idx]) * Mt[idx]
            loss = l.sum() / Mt[idx].sum().clamp_min(1.0)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(idx)
        if (ep + 1) % 10 == 0 or ep == 0:
            print(f"    epoch {ep+1:>3}/{epochs}  loss={tot/n:.4f}")


@torch.no_grad()
def infer_prob(model, X, dev):
    model.eval()
    xt = torch.tensor(X[None], device=dev, dtype=torch.float32) / 5.0
    return torch.sigmoid(model(xt)).squeeze(0).cpu().numpy()


def episode_metrics(seqs, model, dev, thr, tol_ns, ep_by):
    """逐 episode recall / precision（與 Model 2 同協定）。"""
    nt = nh = nd = ndh = 0
    for (name, nid, ep_ns, X, y) in seqs:
        p = infer_prob(model, X, dev)
        det = ep_ns[p >= thr]
        eps = ep_by.get(name, [])
        nt += len(eps); nd += len(det)
        for (s, e) in eps:
            if np.any((det >= s - tol_ns) & (det <= e + tol_ns)):
                nh += 1
        for dt in det:
            if any((s - tol_ns) <= dt <= (e + tol_ns) for (s, e) in eps):
                ndh += 1
    rec = nh / nt if nt else 0.0
    prec = ndh / nd if nd else 0.0
    return dict(episodes=nt, det=nd, recall=rec, precision=prec,
                f1=(2 * rec * prec / (rec + prec) if (rec + prec) else 0.0))


def episode_metrics_from_det(seqs, det_of, tol_ns, ep_by):
    """通用：det_of(name,ep_ns,X)->flagged epoch_ns，回逐-episode R/P。"""
    nt = nh = nd = ndh = 0
    for (name, nid, ep_ns, X, y) in seqs:
        det = det_of(name, ep_ns, X)
        eps = ep_by.get(name, [])
        nt += len(eps); nd += len(det)
        for (s, e) in eps:
            if np.any((det >= s - tol_ns) & (det <= e + tol_ns)):
                nh += 1
        for dt in det:
            if any((s - tol_ns) <= dt <= (e + tol_ns) for (s, e) in eps):
                ndh += 1
    rec = nh / nt if nt else 0.0
    prec = ndh / nd if nd else 0.0
    return dict(episodes=nt, det=nd, recall=rec, precision=prec,
                f1=(2 * rec * prec / (rec + prec) if (rec + prec) else 0.0))


def tight_discrimination(seqs, model, dev, thr, tr_by, tol_ns):
    """乾淨判別力：逐轉換 TP/FP（正=距最近 medium/large 轉換 ±tol 內）。
    不做 episode 膨脹，故不吃 base-rate 紅利。回 P/R/F1 與正樣本 base rate。"""
    tp = fp = pos = tot = 0
    for (name, nid, ep_ns, X, y) in seqs:
        p = infer_prob(model, X, dev)
        tn = tr_by.get(name, np.array([]))
        ytrue = np.zeros(len(ep_ns), bool)
        for t in tn:
            j = int(np.argmin(np.abs(ep_ns - t)))
            if abs(ep_ns[j] - t) <= tol_ns:
                ytrue[j] = True
        pred = p >= thr
        tp += int((pred & ytrue).sum()); fp += int((pred & ~ytrue).sum())
        pos += int(ytrue.sum()); tot += len(ytrue)
    rec = tp / pos if pos else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    return dict(recall=rec, precision=prec,
                f1=(2 * rec * prec / (rec + prec) if (rec + prec) else 0.0),
                base_rate=pos / tot if tot else 0.0)


def model2_baseline(seqs, ep_by, tol_ns, contamination=0.04):
    """同一批 val 衛星上的 IsolationForest 基準（逐轉換，用相同輸入通道）。"""
    from sklearn.ensemble import IsolationForest
    pool = [X for (_, _, _, X, _) in seqs]
    Xall = np.clip(np.nan_to_num(np.vstack(pool)), -200, 200)
    iso = IsolationForest(n_estimators=200, contamination=contamination,
                          random_state=42, n_jobs=-1).fit(Xall)
    nt = nh = nd = ndh = 0
    for (name, nid, ep_ns, X, y) in seqs:
        det = ep_ns[iso.predict(np.clip(np.nan_to_num(X), -200, 200)) == -1]
        eps = ep_by.get(name, [])
        nt += len(eps); nd += len(det)
        for (s, e) in eps:
            if np.any((det >= s - tol_ns) & (det <= e + tol_ns)):
                nh += 1
        for dt in det:
            if any((s - tol_ns) <= dt <= (e + tol_ns) for (s, e) in eps):
                ndh += 1
    rec = nh / nt if nt else 0.0
    prec = ndh / nd if nd else 0.0
    return iso, dict(episodes=nt, det=nd, recall=rec, precision=prec,
                     f1=(2 * rec * prec / (rec + prec) if (rec + prec) else 0.0))


# ────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--max-sats", type=int, default=120)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--win", type=int, default=48)
    ap.add_argument("--tol-hours", type=float, default=24.0)
    ap.add_argument("--train-tol-hours", type=float, default=6.0)
    ap.add_argument("--channels", default="z_drag,z_di,z_de",
                    help="輸入通道（預設丟棄壞掉的 z_draan；設 z_drag,z_di,z_de,z_draan 可復現 4 通道）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--save", default="Orbital_Maneuver_V2/models_meme_anomaly/model3_bigru.pt")
    args = ap.parse_args()

    torch.manual_seed(args.seed); np.random.seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tol_ns = int(args.tol_hours * 3.6e12)
    train_tol_ns = int(args.train_tol_hours * 3.6e12)
    print(f"device={dev}  eval_tol={args.tol_hours}h  train_tol={args.train_tol_hours}h  win={args.win}")

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    print(f"輸入通道={channels}")

    sw = load_space_weather()
    reg = load_registry(args.data_root / "url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    ep_by, tr_by = build_truth(args.data_root)

    # FORMOSAT 永遠排除於訓練/驗證之外（純 OOD holdout）
    all_sats = [(nm, nid) for nm, nid in n2n.items() if int(nid) != FORMOSAT_OOD]
    all_sats = all_sats[: args.max_sats]

    con = duckdb.connect(args.db, read_only=True)
    print(f"載入 {len(all_sats)} 顆物理殘差序列…")
    seqs = load_sequences(con, all_sats, sw, tr_by, train_tol_ns, channels)
    print(f"  有效序列 {len(seqs)} 顆")

    # 依衛星分組 80/20
    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(seqs))
    n_val = max(1, int(0.2 * len(seqs)))
    val_idx = set(order[:n_val].tolist())
    tr = [seqs[i] for i in range(len(seqs)) if i not in val_idx]
    va = [seqs[i] for i in range(len(seqs)) if i in val_idx]
    print(f"  train={len(tr)} 顆  val={len(va)} 顆")

    Xtr, Ytr, Mtr = make_windows(tr, L=args.win)
    model = BiGRULabeler(n_ch=len(channels)).to(dev)
    print("訓練 bi-GRU…")
    train(model, Xtr, Ytr, Mtr, dev, epochs=args.epochs)

    # 門檻掃描：在 val 上選最佳 F1
    print("\n=== 門檻掃描（val，episode F1）===")
    best = None
    for thr in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        m = episode_metrics(va, model, dev, thr, tol_ns, ep_by)
        tag = ""
        if best is None or m["f1"] > best[1]["f1"]:
            best = (thr, m); tag = "  ← best"
        print(f"  thr={thr:.1f}  R={m['recall']:.3f} P={m['precision']:.3f} "
              f"F1={m['f1']:.3f} det={m['det']}{tag}")
    thr_star, m_gru = best

    # 平凡基準：flag-all（每個 epoch 都判機動）→ 揭露 episode 指標的 base-rate 紅利
    m_all = episode_metrics_from_det(va, lambda n, e, X: e, tol_ns, ep_by)
    print(f"\n[平凡基準] flag-ALL：R={m_all['recall']:.3f} P={m_all['precision']:.3f} "
          f"F1={m_all['f1']:.3f}  ← episode 指標下限（bi-GRU 須明顯勝過此值才有意義）")

    # 乾淨判別力（逐轉換，不吃 base-rate 紅利）
    dt_gru = tight_discrimination(va, model, dev, thr_star, tr_by, train_tol_ns)
    print(f"[乾淨判別] bi-GRU 逐轉換：R={dt_gru['recall']:.3f} P={dt_gru['precision']:.3f} "
          f"F1={dt_gru['f1']:.3f}（正樣本 base_rate={dt_gru['base_rate']:.3f}）")

    # Model 2 基準（同 val 衛星）
    print("\n=== Model 2 (IsolationForest) 基準（同 val 衛星）===")
    iso, m_iso = model2_baseline(va, ep_by, tol_ns)
    print(f"  R={m_iso['recall']:.3f} P={m_iso['precision']:.3f} "
          f"F1={m_iso['f1']:.3f} det={m_iso['det']}")

    print("\n=== 對比總結（val） ===")
    print(f"  {'模型':<26}{'Recall':>8}{'Prec':>8}{'F1':>8}{'det':>7}")
    print(f"  {'bi-GRU (thr=%.1f)'%thr_star:<26}{m_gru['recall']:>8.3f}"
          f"{m_gru['precision']:>8.3f}{m_gru['f1']:>8.3f}{m_gru['det']:>7}")
    print(f"  {'Model 2 IsolationForest':<26}{m_iso['recall']:>8.3f}"
          f"{m_iso['precision']:>8.3f}{m_iso['f1']:>8.3f}{m_iso['det']:>7}")

    # FORMOSAT OOD 檢查
    print("\n=== FORMOSAT-3A(29052) OOD 檢查（純大氣衰減，期望 flag≈0）===")
    rf = physical_residuals(_load(con, FORMOSAT_OOD), sw)
    Xf = np.clip(np.nan_to_num(rf[channels].to_numpy(np.float32)), -200, 200)
    pf = infer_prob(model, Xf, dev)
    n_gru = int((pf >= thr_star).sum())
    n_iso = int((iso.predict(Xf) == -1).sum())
    print(f"  轉換數={len(rf)}")
    print(f"  bi-GRU(thr={thr_star:.1f})  flag={n_gru} ({100*n_gru/len(rf):.1f}%)  "
          f"max_prob={pf.max():.3f}")
    print(f"  Model 2 IsolationForest    flag={n_iso} ({100*n_iso/len(rf):.1f}%)")
    con.close()

    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "channels": channels,
                "thr": thr_star, "win": args.win, "input_scale": 5.0}, args.save)
    print(f"\n模型已存 → {args.save}")


if __name__ == "__main__":
    main()
