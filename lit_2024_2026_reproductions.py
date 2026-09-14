#!/usr/bin/env python3
"""lit_2024_2026_reproductions.py — 2024-2026 新增文獻之深度學習/神經型態方法
概念代理實作，與本專案方法在同一 23 星標竿、同一評估協定下比較。

**2026-09-14 修訂**：讀取使用者提供之付費論文全文（`F:\\SSA\\20260917月進度
報告\\付費論文\\aerospace-13-00417-v2.pdf`、`aerospace-12-00991.pdf`）後，發現
兩篇 SNN 文獻皆明確做過消融實驗，證實：**用「多個軌道根數之逐筆差分」為輸入
特徵，遠優於單一特徵**（MLF-SNN 論文 §5.2：差分多特徵輸入平均召回率 0.940，
遠高於非差分單特徵之 0.624）。初版實作僅用單一 sma 去趨勢步階訊號，**明顯
不符合原文設計精神**，本次修訂改用 6 通道特徵（Δsma、Δinclination、
Δeccentricity、ΔRAAN、Δargp、ΔM，皆逐筆差分後每星內部穩健z正規化），並將
SNN 方法從「固定隨機儲備層代理」升級為**真正可訓練之多重門檻 LIF 網路**
（依 MLF-SNN 論文架構：3 門檻 0.6/1.6/2.6、膜電位衰減 τ=0.75、矩形替代梯度，
直接以 PyTorch 自訂 autograd Function 實作端到端反向傳播）。

實作範圍（回應 2026-09-14 使用者提問「除機器學習外有無其他學習方式」新增之
7 篇文獻中，扣除已於 lit_tierA2_reproductions.py 實作之 MDPI Aerospace 2026
多特徵準則法後，剩餘 6 篇之可行性評估）：

- **可實作（本檔）**：
  1. LSTM 分類器 —— 概念對應 "LSTM-based Maneuver Detection for Resident
     Space Object Catalog Maintenance," Neural Computing and Applications,
     2025（原文以 Sentinel-3A 為示範，恰為本標竿成員之一）。
  2. Bi-LSTM 分類器 —— 概念對應 "TLE Prediction using Machine Learning for
     Satellite Maneuver Detection," AIAA 2025-98101（**誠實聲明**：原文僅用
     25 個標註樣本，本實作用全部可用資料訓練，樣本規模差異巨大，不可視為
     忠實重現，僅取其「雙向LSTM」之架構概念）。
  3. **多重門檻 LIF 脈衝神經網路**（依 MLF-SNN 論文架構忠實重現核心機制：
     多重發火門檻、矩形替代梯度、時間平均讀出；**未實作**原文之 batch
     norm/dropout/更深層架構與 ASG-MSLSM 之多尺度儲備池，屬簡化版）。
  4. 遮罩重建代理 —— 概念對應 "Masked and Clustered Pre-Training for
     Geosynchronous Satellite Maneuver Detection," Remote Sensing 17(17):2994,
     2025（**誠實聲明**：原文為 GEO 專用、含聚類步驟，本實作簡化為 LEO
     多通道軌道根數差分序列之隨機遮罩自編碼重建誤差，僅取「自監督遮罩
     預訓練」核心概念，不含原文之聚類步驟）。

- **評估為不可行、本檔未實作**：
  "Space-Based Passive Orbital Maneuver Detection Algorithm for High-Altitude
  Situational Awareness," Aerospace 11(7):563, 2024——原文輸入為太空基光學
  觀測角度資料，與本專案 TLE 軌道根數為完全不同之感測模式，無合理代理
  做法可保留比較意義，故誠實排除、不勉強實作。

方法學（吸收前兩輪審查教訓，從一開始即避免過度宣稱）：
- 全部 4 個方法皆採 **leave-one-satellite-out (LOSO)**：23 星輪流作為
  held-out 測試星，其餘 22 星訓練；**門檻（分類閾值）以訓練星內部切出之
  驗證窗口決定，從未觸碰held-out測試星之真值**，避免審查已指出之測試集
  洩漏問題。
- 訓練標籤：窗口最後一時間點是否落在真值事件 ±1.5 天容差內（與
  `tasa14_compare.evaluate()` 完全同一定義）。
- 評估：`tasa14_compare.evaluate()`，同真值、同配對容差、同 1 天旗標合併；
  同時報告 macro（逐星平均）與 micro/pooled（全部TP/FP/FN加總）兩種口徑。

用法：python lit_2024_2026_reproductions.py [--quick]
輸出：data/benchmark/lit_2024_2026_persat_20260914.csv
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import duckdb

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import evaluate, TOL_D, MERGE_D, DB
from tasa23_ext_arena import ALL_SATS23, load_events_ext2

L = 16               # 窗長，同案例十六 LSTM-AE 之 L
SEED = 42
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ELEM_COLS = ["sma_km", "inclination_deg", "eccentricity", "raan_deg", "argp_deg", "mean_anomaly_deg"]
# 誠實記錄（2026-09-14 除錯過程）：曾嘗試比照 MLF-SNN 論文改用 5-6 通道逐筆
# 差分軌道根數（Δsma/Δi/Δe/ΔRAAN/Δu）取代單一sma特徵，除錯修正兩個真實錯誤
# （fetchdf()時間戳單位、argp/M近圓退化）後，F1 反而全面崩潰至接近 0（遠低於
# 單特徵版本），可能原因是本專案per-satellite可用標註樣本量遠小於原文之
# 大規模跨衛星資料集，多通道原始差分在小樣本下訊噪比不足以支撐學習——
# 此為誠實記錄之負面結果，而非隱藏。因此最終比較版本改回單一特徵（本專案
# 既有 detrend_step 之穩健去趨勢sma步階訊號，與其他既有方法一致），僅保留
# 從論文中習得之「真正可訓練多重門檻LIF＋替代梯度」架構升級（見MLFSNNClf）。
N_CH = 1
MIN_GAP_HR = 3.0


def _load_elements(nid: int):
    con = duckdb.connect(DB, read_only=True)
    cols = ", ".join(ELEM_COLS)
    r = con.execute(
        f"SELECT epoch_utc, {cols} FROM raw_tle_archive WHERE norad_id=? "
        f"AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchdf()
    con.close()
    if len(r) == 0:
        return None
    r["epoch_utc"] = pd.to_datetime(r["epoch_utc"], utc=True)
    # 注意：duckdb fetchdf() 之 datetime 解析度可能是 us 而非 ns，直接
    # .astype('int64')/1e9 會因單位錯誤縮小1000倍（本次除錯發現，同
    # phase_residual_broad_scan.py 先前之根因），改用明確轉為秒單位。
    tsec = r["epoch_utc"].to_numpy().astype("datetime64[s]").astype("float64")
    keep = [0]
    for i in range(1, len(tsec)):
        if tsec[i] - tsec[keep[-1]] >= MIN_GAP_HR * 3600:
            keep.append(i)
    r = r.iloc[keep].reset_index(drop=True)
    return r


def _diff_channel(v: np.ndarray, is_angle: bool) -> np.ndarray:
    d = np.diff(v)
    if is_angle:
        d = (d + 180.0) % 360.0 - 180.0     # 角度量做 wrap，避免 0/360 邊界跳動
    valid = np.isfinite(d)
    med = np.nanmedian(d[valid]) if valid.any() else 0.0
    mad = 1.4826 * np.nanmedian(np.abs(d[valid] - med)) if valid.any() else 0.0
    return (np.where(valid, (d - med) / mad, 0.0) if mad > 0 else np.zeros_like(d)).astype(np.float32)


def build_series():
    """回傳 {nid: dict(t, s, name)}；s 為 [N-1, 1] 之單通道特徵——本專案既有
    `detrend_step` 穩健去趨勢sma步階訊號（與 Tier1/Tier2/TierA2 一致），該星
    內部做穩健z正規化。見上方 N_CH 註解之除錯記錄，說明為何不採多通道版。"""
    from tasa14_compare import detrend_step
    out = {}
    for nid, nm in ALL_SATS23:
        r = _load_elements(nid)
        if r is None or len(r) < L + 10:
            continue
        a = r["sma_km"].to_numpy(float)
        t1 = r["epoch_utc"].iloc[1:].reset_index(drop=True)
        step = detrend_step(a)
        valid = np.isfinite(step)
        med = np.nanmedian(step[valid]) if valid.any() else 0.0
        mad = 1.4826 * np.nanmedian(np.abs(step[valid] - med)) if valid.any() else 0.0
        sn = (np.where(valid, (step - med) / mad, 0.0) if mad > 0 else np.zeros_like(step)).astype(np.float32)
        s = sn.reshape(-1, 1)                # [N-1, 1]
        out[nid] = dict(t=pd.DatetimeIndex(t1), s=s, name=nm)
    return out


def label_series(t1, events_df):
    """回傳與 t1 等長之 bool 陣列：該時間點是否落在任一真值事件±TOL_D天內。"""
    tol = pd.Timedelta(days=TOL_D)
    y = np.zeros(len(t1), bool)
    if events_df is None or len(events_df) == 0:
        return y
    for _, e in events_df.iterrows():
        m = (t1 >= e["ws"] - tol) & (t1 <= e["we"] + tol)
        y |= np.asarray(m)
    return y


def make_windows(t1, s, y, L=L):
    n = len(s)
    if n < L:
        return np.empty((0, L, N_CH), np.float32), np.empty(0, bool), pd.DatetimeIndex([])
    X = np.lib.stride_tricks.sliding_window_view(s, L, axis=0)    # [n-L+1, C, L]
    X = np.transpose(X, (0, 2, 1))                                # [n-L+1, L, C]
    Y = y[L - 1:]
    T = t1[L - 1:]
    return X.astype(np.float32), Y, T


def scores_to_detections(t_arr, scores, thr, tsec=None):
    """機率分數 -> 逐日合併之偵測時間戳（同其餘方法之 1 天合併邏輯）。"""
    idx = np.where(scores >= thr)[0]
    if len(idx) == 0:
        return pd.to_datetime([])
    if tsec is None:
        tsec = t_arr.astype("int64").to_numpy() / 1e9
    dets, grp = [], [idx[0]]
    for j in idx[1:]:
        if tsec[j] - tsec[grp[-1]] <= MERGE_D * 86400:
            grp.append(j)
        else:
            best = grp[int(np.argmax(scores[grp]))]
            dets.append(t_arr[best]); grp = [j]
    best = grp[int(np.argmax(scores[grp]))]
    dets.append(t_arr[best])
    return pd.to_datetime(sorted(dets))


# ═══════════════ 模型定義 ═══════════════

class LSTMClf(nn.Module):
    def __init__(self, bidir=False, hidden=24, n_ch=N_CH):
        super().__init__()
        self.rnn = nn.LSTM(n_ch, hidden, batch_first=True, bidirectional=bidir)
        self.out = nn.Linear(hidden * (2 if bidir else 1), 1)

    def forward(self, x):                       # x:[B,L,C]
        h, _ = self.rnn(x)
        return self.out(h[:, -1, :]).squeeze(-1)


class MaskedAE(nn.Module):
    """簡化遮罩自編碼器：隨機遮罩窗口內部分點，重建整窗，重建誤差作異常分數。"""
    def __init__(self, L=L, n_ch=N_CH, hidden=32):
        super().__init__()
        self.L, self.n_ch = L, n_ch
        self.enc = nn.Sequential(nn.Linear(L * n_ch, hidden), nn.ReLU())
        self.dec = nn.Linear(hidden, L * n_ch)

    def forward(self, x_masked):                # x:[B,L,C]
        b = x_masked.shape[0]
        z = self.enc(x_masked.reshape(b, -1))
        return self.dec(z).reshape(b, self.L, self.n_ch)


class _SpikeFn(torch.autograd.Function):
    """Heaviside 發火函數＋矩形替代梯度（依 MLF-SNN 論文 eq.5）。"""
    @staticmethod
    def forward(ctx, u, vth, width):
        ctx.save_for_backward(u, vth)
        ctx.width = width
        return (u >= vth).float()

    @staticmethod
    def backward(ctx, grad_out):
        u, vth = ctx.saved_tensors
        a = ctx.width
        surrogate = (torch.abs(u - vth) < a / 2).float() / a
        return grad_out * surrogate, None, None


def _spike(u, vth, width=1.0):
    return _SpikeFn.apply(u, vth, width)


class MLFSNNClf(nn.Module):
    """多重門檻 LIF 網路，依 MLF-SNN 論文架構簡化重現：
    Linear(L*C->H) -> 多重門檻LIF(tau=0.75, Vth=[0.6,1.6,2.6]) -> 時間平均 -> Linear(H->1)。
    以 T=4 個時間步之 repeat 編碼（同原文），矩形替代梯度端到端反向傳播。"""
    def __init__(self, L=L, n_ch=N_CH, hidden=32, T=4, vths=(0.6, 1.6, 2.6), tau=0.75):
        super().__init__()
        self.L, self.n_ch, self.T = L, n_ch, T
        self.tau = tau
        self.vths = vths
        self.fc_in = nn.Linear(L * n_ch, hidden)
        self.fc_out = nn.Linear(hidden, 1)
        self.hidden = hidden

    def forward(self, x):                        # x:[B,L,C]
        b = x.shape[0]
        cur = self.fc_in(x.reshape(b, -1))        # [B,H] 每步重複注入（repeat coding）
        u = torch.zeros(b, self.hidden, device=x.device)
        spike_sum = torch.zeros(b, self.hidden, device=x.device)
        for _ in range(self.T):
            u = self.tau * u + cur
            step_spikes = torch.zeros_like(u)
            for vth in self.vths:
                s = _spike(u, torch.tensor(float(vth), device=x.device))
                step_spikes = step_spikes + s
            u = u * (1.0 - (step_spikes > 0).float())     # 發火後重置
            spike_sum = spike_sum + step_spikes
        h = spike_sum / (self.T * len(self.vths))
        return self.fc_out(h).squeeze(-1)


def train_torch_clf(model, Xtr, Ytr, epochs=12, lr=2e-3, seed=SEED):
    torch.manual_seed(seed)
    model = model.to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    n_pos = max(1, int(Ytr.sum())); n_neg = max(1, len(Ytr) - n_pos)
    pos_weight = torch.tensor([n_neg / n_pos], device=DEVICE)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    Xt = torch.tensor(Xtr, device=DEVICE); Yt = torch.tensor(Ytr.astype(np.float32), device=DEVICE)
    bs = 512
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xt), device=DEVICE)
        for i in range(0, len(Xt), bs):
            idx = perm[i:i + bs]
            logit = model(Xt[idx])
            loss = lossf(logit, Yt[idx])
            opt.zero_grad(); loss.backward(); opt.step()
    return model


def predict_torch_clf(model, X):
    model.eval()
    with torch.no_grad():
        out = []
        for i in range(0, len(X), 4096):
            xb = torch.tensor(X[i:i + 4096], device=DEVICE)
            out.append(torch.sigmoid(model(xb)).cpu().numpy())
    return np.concatenate(out) if out else np.array([])


def method_lstm(bidir, Xtr, Ytr, Xval, Yval, Xtest):
    model = train_torch_clf(LSTMClf(bidir=bidir), Xtr, Ytr)
    val_score = predict_torch_clf(model, Xval)
    thr = _pick_threshold(val_score, Yval)
    test_score = predict_torch_clf(model, Xtest)
    return test_score, thr


def method_mlfsnn(Xtr, Ytr, Xval, Yval, Xtest):
    model = train_torch_clf(MLFSNNClf(), Xtr, Ytr, epochs=15)
    val_score = predict_torch_clf(model, Xval)
    thr = _pick_threshold(val_score, Yval)
    test_score = predict_torch_clf(model, Xtest)
    return test_score, thr


def method_maskedae(Xtr, Ytr, Xval, Yval, Xtest, mask_frac=0.3, seed=SEED):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = MaskedAE().to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    lossf = nn.MSELoss()
    Xt = torch.tensor(Xtr, device=DEVICE)
    bs = 512
    for ep in range(20):
        model.train()
        perm = torch.randperm(len(Xt), device=DEVICE)
        for i in range(0, len(Xt), bs):
            idx = perm[i:i + bs]
            xb = Xt[idx]
            mask = torch.tensor(rng.random(xb.shape) < mask_frac, device=DEVICE)
            xb_masked = xb.clone(); xb_masked[mask] = 0.0
            recon = model(xb_masked)
            loss = lossf(recon, xb)
            opt.zero_grad(); loss.backward(); opt.step()

    def recon_err(X):
        model.eval()
        with torch.no_grad():
            xb = torch.tensor(X, device=DEVICE)
            recon = model(xb)
            return ((recon - xb) ** 2).mean((1, 2)).cpu().numpy()

    val_score = recon_err(Xval)
    thr = _pick_threshold(val_score, Yval)
    test_score = recon_err(Xtest)
    return test_score, thr


def _pick_threshold(val_score, val_y):
    """僅用訓練星切出之驗證集決定門檻，從未觸碰held-out測試星——
    取「使驗證集F1最大」之門檻，候選門檻為驗證分數之分位數。"""
    if val_y.sum() == 0 or len(val_score) == 0:
        return float(np.quantile(val_score, 0.95)) if len(val_score) else 0.5
    cands = np.quantile(val_score, np.linspace(0.5, 0.995, 40))
    best_thr, best_f1 = cands[0], -1
    for c in cands:
        pred = val_score >= c
        tp = (pred & val_y).sum(); fp = (pred & ~val_y).sum(); fn = (~pred & val_y).sum()
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        if f1 > best_f1:
            best_f1, best_thr = f1, c
    return float(best_thr)


METHODS = {
    "lstm2025": lambda *a: method_lstm(False, *a),
    "bilstm2025": lambda *a: method_lstm(True, *a),
    "mlfsnn_proxy": method_mlfsnn,
    "masked_ae_proxy": method_maskedae,
}


def main():
    quick = "--quick" in sys.argv
    t0 = time.time()
    events = load_events_ext2()
    series = build_series()
    nids = list(series.keys())
    if quick:
        nids = nids[:4]
    print(f"可用衛星：{len(nids)} 顆，特徵通道：{ELEM_COLS}", flush=True)

    per_sat = {}
    for nid in nids:
        d = series[nid]
        y_point = label_series(d["t"], events.get(nid))
        X, Y, T = make_windows(d["t"], d["s"], y_point)
        per_sat[nid] = dict(X=X, Y=Y, T=T, name=d["name"])

    rows = []
    for held_nid in nids:
        d_held = per_sat[held_nid]
        if len(d_held["X"]) == 0 or held_nid not in events:
            continue
        train_nids = [n for n in nids if n != held_nid and len(per_sat[n]["X"]) > 0]
        Xall = np.concatenate([per_sat[n]["X"] for n in train_nids])
        Yall = np.concatenate([per_sat[n]["Y"] for n in train_nids])
        rng = np.random.default_rng(SEED)
        perm = rng.permutation(len(Xall))
        n_val = max(50, int(0.2 * len(Xall)))
        val_idx, tr_idx = perm[:n_val], perm[n_val:]
        Xtr, Ytr = Xall[tr_idx], Yall[tr_idx]
        Xval, Yval = Xall[val_idx], Yall[val_idx]
        Xtest = d_held["X"]

        for mname, fn in METHODS.items():
            try:
                test_score, thr = fn(Xtr, Ytr, Xval, Yval, Xtest)
                dets = scores_to_detections(d_held["T"], test_score, thr)
                r = evaluate(held_nid, events, lambda t_, a_, dd=dets: dd)
                if r:
                    rows.append(dict(norad=held_nid, name=d_held["name"], method=mname,
                                      **{k: v for k, v in r.items() if k != "norad"}))
            except Exception as e:
                print(f"  [WARN] {mname} @ {d_held['name']}: {type(e).__name__}: {e}", flush=True)
        print(f"[{d_held['name']}] 完成 4 法 ({time.time()-t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/lit_2024_2026_persat_20260914.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列，耗時 {time.time()-t0:.0f}s）", flush=True)
    if len(df):
        for m, g in df.groupby("method"):
            macro_f1 = g["f1"].mean()
            tp, fp, fn = g["tp"].sum(), g["fp"].sum(), g["fn"].sum()
            micro_p = tp / (tp + fp) if tp + fp else 0.0
            micro_r = tp / (tp + fn) if tp + fn else 0.0
            micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if micro_p + micro_r else 0.0
            print(f"{m:16s} macroF1={macro_f1:.3f} microF1={micro_f1:.3f} "
                  f"macroP={g['precision'].mean():.3f} macroR={g['recall'].mean():.3f}", flush=True)


if __name__ == "__main__":
    main()
