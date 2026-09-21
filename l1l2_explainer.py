#!/usr/bin/env python3
"""
l1l2_explainer.py
=================
StoryMap 案例二十七用：把 L1（P1–P6 規則）與 L2（CUSUM／BOCPD／SSA／MAD 3σ）
兩層偵測法，以「TLE 逐筆到來」的 Plotly 動畫呈現。

全部沿用專案既有實作，不另寫偵測邏輯：
  L1 = maneuver_strategies_july.build_transitions / apply_strategies
  L2 = statistical_detectors.run_all

注意：L1 逐筆只看相鄰兩筆與短窗，天然可線上運作；L2 的 SSA／MAD 使用整段序列統計量，
動畫中的「逐步揭露」是把整段已算好的分數依時間顯示，並非嚴格線上重算。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pathlib import Path

import maneuver_strategies_july as ms
from statistical_detectors import run_all

MAX_FRAMES = 70
COL_OK, COL_FLAG, COL_SUP, COL_MUTED = "#5b8def", "#e5484d", "#9aa0a6", "#c7cbd1"


def _thin(d: pd.DataFrame, min_gap_h: float, max_pts: int) -> pd.DataFrame:
    """稀釋近重複 epoch（同論文 §2.1 做法），再取最近 max_pts 筆，控制動畫檔大小。"""
    keep, last = [], None
    for i, e in enumerate(d["epoch"]):
        if last is None or (e - last).total_seconds() >= min_gap_h * 3600:
            keep.append(i)
            last = e
    return d.iloc[keep].tail(max_pts).reset_index(drop=True)


def prepare(df: pd.DataFrame, f107: dict | None = None, p2_scale: float = 1.0,
            days: int | None = None, min_gap_h: float = 12.0, max_pts: int = 450) -> dict | None:
    """由 load_tle() 之 DataFrame 算出 L1、L2 全部逐點結果；資料不足回 None。"""
    if df is None or df.empty:
        return None
    d = df.sort_values("epoch").reset_index(drop=True)
    if days:
        d = d[d["epoch"] >= d["epoch"].max() - pd.Timedelta(days=days)].reset_index(drop=True)
    raw = d[["epoch", "sma_km"]].copy()          # 原始取樣（L3 通道分數需與訓練同尺度，不稀釋）
    d = _thin(d, min_gap_h, max_pts)
    if len(d) < 12:
        return None
    a = float(d["sma_km"].iloc[-1])
    orbit = ms.classify_orbit(a, float(d["eccentricity"].iloc[-1]),
                              float(d["inclination_deg"].iloc[-1]))
    p2 = ms.ParabolaParams(ms.DEFAULT_P2.vertex, ms.DEFAULT_P2.floor * p2_scale,
                           ms.DEFAULT_P2.ref_x, ms.DEFAULT_P2.ref_y * p2_scale)
    tr = ms.build_transitions(d, f107 or None)
    if tr.empty:
        return None
    st_ = ms.apply_strategies(tr, orbit, p2=p2)
    det = run_all(d["sma_km"].to_numpy(float))
    return {"d": d, "raw": raw, "tr": tr, "strat": st_, "det": det, "orbit": orbit,
            "alt_km": float(d["sma_km"].mean() - ms.R_E), "n_tle": len(d)}


def _naive(ts: pd.Series) -> pd.Series:
    """UTC 時間 → 無時區、取整秒：避免 Plotly 對「+00:00＋微秒」字串的範圍解析異常。"""
    return pd.to_datetime(ts, utc=True).dt.tz_convert(None).dt.floor("s")


def _steps(n: int) -> list[int]:
    step = max(1, int(np.ceil(n / MAX_FRAMES)))
    ks = list(range(step, n + 1, step))
    if not ks or ks[-1] != n:
        ks.append(n)
    return ks


def _play_layout(fig: go.Figure, ks: list[int], labels: list[str], T, height: int, prefix: str | None = None) -> None:
    fig.update_layout(
        height=height, margin=dict(l=50, r=20, t=30, b=40), showlegend=False,
        updatemenus=[dict(
            type="buttons", direction="left", x=0.0, y=-0.06, xanchor="left", yanchor="top",
            buttons=[
                dict(label=T("▶ 播放", "▶ 再生", "▶ Play"), method="animate",
                     args=[None, dict(frame=dict(duration=140, redraw=True), fromcurrent=True,
                                      transition=dict(duration=0))]),
                dict(label=T("⏸ 暫停", "⏸ 停止", "⏸ Pause"), method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate",
                                        transition=dict(duration=0))]),
            ])],
        sliders=[dict(
            x=0.18, len=0.8, y=-0.04, pad=dict(t=0, b=0),
            currentvalue=dict(prefix=prefix or T("已到達 TLE：", "到達TLE：", "TLEs received: ")),
            steps=[dict(method="animate", label=lb,
                        args=[[str(k)], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                             transition=dict(duration=0))])
                   for k, lb in zip(ks, labels)])])


# ── L1：規則閘門 ───────────────────────────────────────────────────────────────
def fig_l1(P: dict, T) -> go.Figure:
    d, tr, S = P["d"], P["tr"], P["strat"]
    ps, comb, thr = S["per_strategy"], S["combined"], S["thr_da"]
    t = _naive(tr["epoch"])
    absda = np.abs(tr["da_km"].to_numpy(float)) * 1000.0     # m
    thr_m = np.asarray(thr, float) * 1000.0
    rules = [("P2", "P2", T("P2 高度門檻", "P2 高度しきい値", "P2 altitude thr.")),
             ("P5", "P5", T("P5 F10.7 倍率", "P5 F10.7倍率", "P5 F10.7 scaling")),
             ("P6", "P6", T("P6 星座基準", "P6 星座基準", "P6 constellation")),
             ("P4", "P4", T("P4 多窗口補漏", "P4 多窓補完", "P4 multi-window")),
             ("other(di/de/dΩ)", "other", T("傾角/離心率/升交點", "傾斜角/離心率/RAAN", "inc/ecc/RAAN")),
             ("P1_suppress", "P1", T("P1 衰減抑制", "P1 減衰抑制", "P1 decay suppress")),
             ("P3_suppress", "P3", T("P3 B*抑制", "P3 B*抑制", "P3 B* suppress"))]
    n = len(tr)
    bar_col = np.where(comb, COL_FLAG, COL_OK)
    sma_m = pd.Series(d["sma_km"].to_numpy(float), index=pd.DatetimeIndex(_naive(d["epoch"])))

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.34, 0.34, 0.32],
                        vertical_spacing=0.06,
                        subplot_titles=(T("① 半長軸 a（km）", "① 軌道長半径 a（km）", "① Semi-major axis a (km)"),
                                        T("② 相鄰 TLE 的 |Δa|（m）vs 門檻", "② 隣接TLEの|Δa|（m）vs しきい値", "② |Δa| between adjacent TLEs (m) vs threshold"),
                                        T("③ 規則亮燈（紅＝偵測、灰＝抑制）", "③ ルール点灯（赤＝検出、灰＝抑制）", "③ Rule lights (red = detect, grey = suppress)")))

    def traces(k):
        out = [
            go.Scatter(x=sma_m.index[sma_m.index <= t.iloc[k - 1]],
                       y=sma_m[sma_m.index <= t.iloc[k - 1]], mode="lines+markers",
                       line=dict(color=COL_OK, width=1.4), marker=dict(size=3)),
            go.Scatter(x=t[:k][comb[:k]], y=tr["sma_km"][:k][comb[:k]], mode="markers",
                       marker=dict(size=11, color=COL_FLAG, symbol="star")),
            go.Bar(x=t[:k], y=absda[:k], marker_color=bar_col[:k]),
            go.Scatter(x=t[:k], y=thr_m[:k], mode="lines", line=dict(color="#111", width=2, dash="dot", shape="hv")),
        ]
        for key, code, _lb in rules:
            m = ps[key][:k]
            sup = key.endswith("suppress")
            out.append(go.Scatter(x=t[:k][m], y=[code] * int(m.sum()), mode="markers",
                                  marker=dict(size=9, symbol="x" if sup else "square",
                                              color=COL_SUP if sup else COL_FLAG)))
        return out

    ks = _steps(n)
    first = traces(ks[0])
    for i, tr_ in enumerate(first):
        fig.add_trace(tr_, row=[1, 1, 2, 2][i] if i < 4 else 3, col=1)
    fig.frames = [go.Frame(data=traces(k), traces=list(range(len(first))), name=str(k)) for k in ks]

    fig.update_xaxes(range=[t.iloc[0], t.iloc[-1]], autorange=False)
    fig.update_yaxes(range=[sma_m.min() - 0.02 * (np.ptp(sma_m) + 1e-3),
                            sma_m.max() + 0.02 * (np.ptp(sma_m) + 1e-3)], row=1, col=1)
    pos = absda[absda > 0]
    lo = max(min(float(pos.min()) if len(pos) else 1.0, float(thr_m.min())) * 0.5, 0.01)
    fig.update_yaxes(type="log", range=[np.log10(lo), np.log10(max(absda.max(), thr_m.max()) * 1.5)],
                     row=2, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=[c for _, c, _ in rules][::-1],
                     row=3, col=1)
    _play_layout(fig, ks, [str(k) for k in ks], T, 720)
    return fig


# ── L2：四個統計通道 ───────────────────────────────────────────────────────────
def fig_l2(P: dict, T) -> go.Figure:
    d, det = P["d"], P["det"]
    t = _naive(d["epoch"])
    sma = d["sma_km"].to_numpy(float)
    n = len(d)
    chans = [("cusum", "CUSUM", T("累積和：均值有沒有偷偷偏移", "累積和：平均が静かにずれていないか", "Cumulative sum: has the mean drifted?")),
             ("bocpd", "BOCPD", T("貝氏變點：此刻是新狀態的機率", "ベイズ変化点：今が新状態である確率", "Bayesian change-point: chance we are in a new regime")),
             ("ssa", "SSA", T("奇異譜：扣掉趨勢與週期後的殘差尖峰", "特異スペクトル：傾向と周期を除いた残差スパイク", "SSA: residual spikes after trend + oscillation")),
             ("mad3sig", "MAD 3σ", T("穩健 3σ：這一步是否離群", "ロバスト3σ：この一歩は外れ値か", "Robust 3σ: is this step an outlier?"))]
    sc = {k: np.abs(np.nan_to_num(np.asarray(det[k]["scores"], float))) for k, _, _ in chans}
    # 序列起點前幾筆為偵測器暖機（如 BOCPD 初始 run-length 先驗），不當作事件顯示
    ev = {k: (lambda e: e[e >= 3])(np.asarray(det[k]["events"], int)) for k, _, _ in chans}

    fig = make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.045,
                        subplot_titles=(T("半長軸 a（km）", "軌道長半径 a（km）", "Semi-major axis a (km)"),
                                        *[f"{lb}　{ds}" for _, lb, ds in chans]))

    def traces(k):
        out = [go.Scatter(x=t[:k], y=sma[:k], mode="lines+markers",
                          line=dict(color=COL_OK, width=1.4), marker=dict(size=3))]
        for key, _, _ in chans:
            e = ev[key][ev[key] < k]
            out.append(go.Scatter(x=t[:k], y=sc[key][:k], mode="lines",
                                  line=dict(color="#7a5af8", width=1.4)))
            out.append(go.Scatter(x=t.iloc[e], y=sc[key][e], mode="markers",
                                  marker=dict(size=10, color=COL_FLAG, symbol="star")))
        return out

    ks = _steps(n)
    first = traces(ks[0])
    rows = [1] + [r for r in range(2, 6) for _ in (0, 1)]
    for tr_, r in zip(first, rows):
        fig.add_trace(tr_, row=r, col=1)
    fig.frames = [go.Frame(data=traces(k), traces=list(range(len(first))), name=str(k)) for k in ks]
    fig.update_xaxes(range=[t.iloc[0], t.iloc[-1]], autorange=False)
    pad = 0.02 * (np.ptp(sma) + 1e-3)
    fig.update_yaxes(range=[sma.min() - pad, sma.max() + pad], row=1, col=1)
    for r, (key, _, _) in enumerate(chans, start=2):
        fig.update_yaxes(range=[0, max(float(sc[key].max()) * 1.15, 1e-6)], row=r, col=1)
    _play_layout(fig, ks, [str(k) for k in ks], T, 860)
    return fig


# ── L3：候選確認式（L1／L2 類偵測器提出候選 → L3 逐一確認或否決）──────────────────
_L3_CACHE: dict = {}
L3_MODELS = {"leo_altimetry": "l3_altimetry.pkl", "starlink": "l3_starlink.pkl"}
L3_ABLATE = ["z_ls", "z_pe", "z_step", "s_cusum", "s_bocpd", "s_ssa", "s_mad", "det_it2", "det_pr"]


def load_l3(family: str):
    """讀 models_fusion/l3_altimetry.pkl（非 Starlink）或 l3_starlink.pkl；缺檔或版本不符回 None。"""
    if family not in _L3_CACHE:
        try:
            import joblib
            _L3_CACHE[family] = joblib.load(Path(__file__).with_name("models_fusion") / L3_MODELS[family])
        except Exception:
            _L3_CACHE[family] = None
    return _L3_CACHE[family]


def compute_l3c(tle_df: pd.DataFrame, P: dict, family: str) -> dict | None:
    """以 l3_candidate 對完整 TLE 序列產生候選與特徵，L3 逐一給機率並依 θ 確認／否決。

    tle_df：完整歷史（epoch, sma_km）——σ 正規化特徵需要足夠長的序列；顯示時再截到 P 的觀察窗。
    ablation：把單一特徵歸零後機率掉多少（＝該特徵對此候選決策的貢獻）。
    """
    M = load_l3(family)
    if M is None:
        return None
    import l3_candidate as C
    t, a = C.to_series(tle_df)
    cand = C.build_candidates(t, a)
    if cand.empty:
        return None
    clf, feats = M["clf"], M["feats"]
    cls = C.cadence_class(float(cand["cadence_d"].iloc[0]))
    theta = float(M["theta"][cls])
    X = cand[feats].astype(float)                 # 保留欄名（模型以 DataFrame 訓練）
    p = clf.predict_proba(X)[:, 1]
    drop = np.zeros((len(cand), len(L3_ABLATE)))
    for j, f in enumerate(L3_ABLATE):
        Xm = X.copy()
        Xm[f] = 0.0
        drop[:, j] = p - clf.predict_proba(Xm)[:, 1]
    # 顯示窗：與 L1／L2 動畫同一觀察範圍
    t0, t1 = P["d"]["epoch"].min(), P["d"]["epoch"].max()
    ep = pd.to_datetime(cand["epoch"], utc=True)
    show = ((ep >= t0) & (ep <= t1)).to_numpy()
    # L1：P1–P6 combined 旗標在候選 ±1 天內？
    tr_ep = pd.to_datetime(P["tr"]["epoch"], utc=True)[np.asarray(P["strat"]["combined"], bool)]
    en = pd.DatetimeIndex(ep).as_unit("ns").astype("int64").to_numpy()
    l1n = pd.DatetimeIndex(tr_ep).as_unit("ns").astype("int64").to_numpy() if len(tr_ep) else np.array([], dtype="int64")
    day = int(86400e9)
    l1 = np.array([bool(len(l1n)) and bool(np.min(np.abs(l1n - c)) <= day) for c in en])
    l2 = (cand[["src_cusum", "src_bocpd", "src_ssa", "src_mad3sig"]].sum(axis=1) > 0).to_numpy()
    return {"cand": cand[show].reset_index(drop=True), "proba": p[show], "acc": (p >= theta)[show],
            "drop": drop[show], "theta": theta, "cls": cls, "l1": l1[show], "l2": l2[show],
            "family": family, "n_all": int(len(cand)),
            "model": {k: M.get(k) for k in ("loso", "n_sats", "n_candidates", "trained_on", "family")}}


def fig_l3c(P: dict, L: dict, T) -> go.Figure:
    d = P["d"]
    t_sma = _naive(d["epoch"])
    sma = d["sma_km"].to_numpy(float)
    cand, p, acc, drop, thr = L["cand"], L["proba"], L["acc"], L["drop"], L["theta"]
    n = len(cand)
    tc = _naive(cand["epoch"])
    a_at = np.interp(pd.DatetimeIndex(tc).as_unit("ns").asi8.astype("float64"), pd.DatetimeIndex(t_sma).as_unit("ns").asi8.astype("float64"), sma)
    lab = [T(*C_LABELS[f]) for f in L3_ABLATE]
    src_names = [("src_iter2", "iter2"), ("src_pred", "pred"), ("src_cusum", "CUSUM"), ("src_bocpd", "BOCPD"),
                 ("src_ssa", "SSA"), ("src_mad3sig", "MAD3σ")]
    fig = make_subplots(
        rows=4, cols=2, vertical_spacing=0.075, horizontal_spacing=0.2,
        row_heights=[0.24, 0.30, 0.24, 0.16],
        specs=[[{"colspan": 2}, None], [{}, {}], [{"colspan": 2}, None], [{"colspan": 2}, None]],
        subplot_titles=(
            T("① 半長軸 a：偵測器提出的候選（灰）→ L3 確認（紅星）／否決（灰叉）；橘＝目前這一個",
              "① 長半径 a：検出器が挙げた候補（灰）→ L3が確認（赤星）／却下（灰×）；橙＝現在の候補",
              "① Semi-major axis a: candidates proposed by detectors (grey) → confirmed (red star) / rejected (grey ×) by L3; orange = current"),
            T("② 目前候選的特徵（長度＝log(1+值)，文字＝原值）", "② 現在の候補の特徴（長さ＝log(1+値)、文字＝元の値）",
              "② Features of the current candidate (length = log(1+value), text = raw value)"),
            T("③ 把該特徵歸零後機率掉多少（＝貢獻）", "③ その特徴を0にした時の確率低下（＝寄与）",
              "③ Probability drop if the feature is zeroed (= contribution)"),
            T("④ L3 對每個候選的確認機率 vs 門檻（虛線）", "④ 各候補に対するL3の確認確率 vs しきい値（点線）",
              "④ L3's confirmation probability per candidate vs threshold (dotted)"),
            T("⑤ 同一候選：L1、L2、L3 各自是否成立", "⑤ 同じ候補：L1・L2・L3がそれぞれ成立したか",
              "⑤ Same candidates: did L1, L2, L3 each fire?")))

    def traces(k):
        j = k - 1
        f = cand.loc[j, L3_ABLATE].to_numpy(float)
        srcs = ", ".join(nm for col, nm in src_names if cand.loc[j, col] == 1) or "—"
        tsel = tc[:k]
        out = [
            go.Scatter(x=t_sma, y=sma, mode="lines", line=dict(color=COL_OK, width=1.2)),
            go.Scatter(x=tsel[~acc[:k]], y=a_at[:k][~acc[:k]], mode="markers", marker=dict(size=8, symbol="x", color=COL_SUP)),
            go.Scatter(x=tsel[acc[:k]], y=a_at[:k][acc[:k]], mode="markers", marker=dict(size=13, symbol="star", color=COL_FLAG)),
            go.Scatter(x=[tc.iloc[j]], y=[a_at[j]], mode="markers", marker=dict(size=17, color="rgba(245,159,0,0)", line=dict(width=3, color="#f59f00")),
                       hovertext=[T("提出者：", "提案元：", "Proposed by: ") + srcs], hoverinfo="text"),
            go.Bar(x=np.log1p(f), y=lab, orientation="h", marker_color=COL_OK, text=[f"{v:.3g}" for v in f], textposition="outside"),
            go.Bar(x=drop[j], y=lab, orientation="h", marker_color=[COL_FLAG if v > 0 else COL_MUTED for v in drop[j]]),
            go.Scatter(x=tsel, y=p[:k], mode="markers", marker=dict(size=8, color=np.where(acc[:k], COL_FLAG, COL_SUP))),
        ]
        for name, arr in (("L1", L["l1"]), ("L2", L["l2"]), ("L3", acc)):
            m = arr[:k]
            out.append(go.Scatter(x=tsel[m], y=[name] * int(m.sum()), mode="markers", marker=dict(size=9, symbol="square", color=COL_FLAG)))
        return out

    ks = _steps(n)
    first = traces(ks[0])
    pos = [(1, 1), (1, 1), (1, 1), (1, 1), (2, 1), (2, 2), (3, 1), (4, 1), (4, 1), (4, 1)]
    for tr_, (r, c) in zip(first, pos):
        fig.add_trace(tr_, row=r, col=c)
    fig.add_trace(go.Scatter(x=[tc.iloc[0], tc.iloc[-1]], y=[thr, thr], mode="lines", line=dict(color="#111", width=2, dash="dot")), row=3, col=1)
    fig.frames = [go.Frame(data=traces(k), traces=list(range(len(first))), name=str(k)) for k in ks]
    x0, x1 = _naive(d["epoch"]).iloc[0], _naive(d["epoch"]).iloc[-1]
    for r in (1, 3, 4):
        fig.update_xaxes(range=[x0, x1], autorange=False, row=r, col=1)
    pad = 0.02 * (np.ptp(sma) + 1e-3)
    fig.update_yaxes(range=[sma.min() - pad, sma.max() + pad], row=1, col=1)
    fig.update_yaxes(autorange="reversed", row=2, col=1)
    fig.update_yaxes(autorange="reversed", row=2, col=2)
    fmax = float(np.log1p(cand[L3_ABLATE].to_numpy(float)).max()) * 1.35 + 1e-6
    fig.update_xaxes(range=[0, fmax], row=2, col=1)
    dl = max(float(np.abs(drop).max()), 0.05) * 1.1
    fig.update_xaxes(range=[-dl, dl], zeroline=True, row=2, col=2)
    fig.update_yaxes(range=[-0.02, 1.02], row=3, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=["L3", "L2", "L1"], row=4, col=1)
    _play_layout(fig, ks, [str(k) for k in ks], T, 1020, prefix=T("已處理候選：", "処理した候補：", "Candidates processed: "))
    return fig


C_LABELS = {
    "z_ls": ("位準位移 SNR", "レベルシフトSNR", "Level-shift SNR"),
    "z_pe": ("預測誤差 SNR", "予測誤差SNR", "Prediction-error SNR"),
    "z_step": ("單步 |Δa| SNR", "1ステップ|Δa| SNR", "Single-step |Δa| SNR"),
    "s_cusum": ("CUSUM 分數", "CUSUMスコア", "CUSUM score"),
    "s_bocpd": ("BOCPD 分數", "BOCPDスコア", "BOCPD score"),
    "s_ssa": ("SSA 分數", "SSAスコア", "SSA score"),
    "s_mad": ("MAD 3σ 分數", "MAD 3σスコア", "MAD 3σ score"),
    "det_it2": ("強偵測器 iter2 同意", "強検出器iter2一致", "Strong detector iter2"),
    "det_pr": ("強偵測器 pred 同意", "強検出器pred一致", "Strong detector pred"),
}


def l3c_summary(L: dict) -> dict:
    return {"n": len(L["cand"]), "n_acc": int(L["acc"].sum()), "n_l1": int(L["l1"].sum()),
            "n_l2": int(L["l2"].sum()), "theta": L["theta"], "cls": L["cls"], "max": float(L["proba"].max()) if len(L["proba"]) else 0.0}


def summary(P: dict) -> dict:
    """給頁面旁白用的數字。"""
    tr, S, det = P["tr"], P["strat"], P["det"]
    return {"n_tle": P["n_tle"], "alt_km": P["alt_km"], "orbit": P["orbit"],
            "l1_flags": int(S["combined"].sum()), "l1_transitions": len(tr),
            "l1_suppressed": int((S["per_strategy"]["P1_suppress"] | S["per_strategy"]["P3_suppress"]).sum()),
            "l2_events": {k: int(len(det[k]["events"])) for k in ("cusum", "bocpd", "ssa", "mad3sig")}}
