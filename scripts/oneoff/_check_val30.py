import io, sys, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
df  = pd.read_csv("leo_annotator/output/validation_full.csv")
ok  = df[df["tle_status"] == "ok"].copy()
ok["norad_id"] = ok["norad_id"].astype(str)
ann = pd.read_csv("leo_annotator/output/annotations_leo_full.csv", dtype=str, encoding="utf-8-sig")
ann_p = ann[["norad_id", "propulsion_class"]].drop_duplicates("norad_id")
ok = ok.drop(columns=["propulsion_class"], errors="ignore").merge(ann_p, on="norad_id", how="left")
GT_POS = {"Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other"}
gt  = ok["propulsion_class"].isin(GT_POS)
det = ok["maneuver_detected"].fillna(False).astype(bool)
mw  = ok["multi_window_detected"].fillna(False).astype(bool)
any_det = det | mw
tp = int((gt & any_det).sum()); fp = int((~gt & any_det).sum())
fn = int((gt & ~any_det).sum()); tn = int((~gt & ~any_det).sum())
prec = tp / (tp + fp) if tp + fp > 0 else 0
rec  = tp / (tp + fn) if tp + fn > 0 else 0
f1   = 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0
mono = int(ok["monotone_suppressed"].fillna(False).sum())
spike = int(ok.get("monotone_with_spike", pd.Series([False]*len(ok))).fillna(False).sum())
print("=== 30 天 validate_annotations 結果 ===")
print(f"有效衛星 : {len(ok)}")
print(f"GT+      : {gt.sum()}   GT- : {(~gt).sum()}")
print(f"P1 抑制  : {mono}  spike rescue: {spike}")
print(f"maneuver_detected=True (主偵測) : {det.sum()}")
print(f"Full P1-P4 detected (含多窗口) : {any_det.sum()}")
print(f"TP={tp}  FP={fp}  FN={fn}  TN={tn}")
print(f"Precision={prec:.1%}  Recall={rec:.1%}  F1={f1:.1%}")
pos_neg = ok["maneuver_detected"].fillna(False).value_counts().sort_index().to_dict()
print(f"label_binary dist: {{0: {pos_neg.get(False,0)}, 1: {pos_neg.get(True,0)}}}")
