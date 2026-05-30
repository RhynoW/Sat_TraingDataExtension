"""Patch 25 medium-priority FP satellites based on user research report."""
import numpy as np
import pandas as pd

NAN = np.nan

PATCHES = {
    # Micro/ColdGas
    "57390": ("Micro/ColdGas", "ThrustMe I2T5 iodine cold gas thruster",
              "ManualCorrection", "High",
              "LEMUR-2 MANO: Spire Global 3U CubeSat. ThrustMe I2T5 solid iodine cold gas propulsion, "
              "one of first LEMUR units with propulsion for constellation phasing, CA, deorbit.",
              None, None, None),
    # Electric_EP
    "67378": ("Electric_EP", "Electric propulsion (Kepler AETHER optical relay satellite)",
              "ManualCorrection", "High",
              "AETHER-7: Kepler Communications 300 kg optical data relay satellite. "
              "Electric propulsion for stationkeeping. 4+ optical terminals, Starlink-bus inspired.",
              300.0, "ManualCorrection", "Kepler AETHER-7 ~300 kg"),
    "61189": ("Electric_EP", "Electric propulsion (Chang Guang Satellite Technology)",
              "ManualCorrection", "High",
              "JILIN-01 KUANFU 02B 1: Chang Guang commercial EO satellite, "
              "electric propulsion for orbit maintenance.",
              None, None, None),
    "61191": ("Electric_EP", "Electric propulsion (Chang Guang Satellite Technology)",
              "ManualCorrection", "High",
              "JILIN-01 KUANFU 02B 3: Chang Guang commercial EO satellite, "
              "electric propulsion for orbit maintenance.",
              None, None, None),
    "56961": ("Electric_EP", "ENPULSION IFM Nano FEEP thruster",
              "ManualCorrection", "High",
              "ICEYE-X26: ICEYE X-band SAR satellite. "
              "ENPULSION IFM Nano FEEP (Field Emission Electric Propulsion) for orbit maintenance.",
              None, None, None),
    "56947": ("Electric_EP", "ENPULSION IFM Nano FEEP thruster",
              "ManualCorrection", "High",
              "ICEYE-X30: ICEYE X-band SAR satellite. "
              "ENPULSION IFM Nano FEEP for orbit maintenance and stationkeeping.",
              None, None, None),
    "64587": ("Electric_EP", "Electric propulsion (Argotec HEO platform)",
              "ManualCorrection", "High",
              "IRIDE-MS2-HEO-8: Italian IRIDE ~65 kg hyperspectral EO microsatellite, "
              "Argotec HEO platform with electric propulsion, SSO 500-600 km.",
              65.0, "ManualCorrection", "IRIDE HEO platform ~65 kg"),
    "64568": ("Electric_EP", "Electric propulsion (Argotec HEO platform)",
              "ManualCorrection", "High",
              "IRIDE-MS2-HEO-3: Italian IRIDE ~65 kg hyperspectral EO microsatellite, "
              "Argotec HEO platform with electric propulsion, SSO 500-600 km.",
              65.0, "ManualCorrection", "IRIDE HEO platform ~65 kg"),
    "64585": ("Electric_EP", "Electric propulsion (Argotec HEO platform)",
              "ManualCorrection", "High",
              "IRIDE-MS2-HEO-9: Italian IRIDE ~65 kg hyperspectral EO microsatellite, "
              "Argotec HEO platform with electric propulsion, SSO 500-600 km.",
              65.0, "ManualCorrection", "IRIDE HEO platform ~65 kg"),
    "64582": ("Electric_EP", "Electric propulsion (Argotec HEO platform)",
              "ManualCorrection", "High",
              "IRIDE-MS2-HEO-4: Italian IRIDE ~65 kg hyperspectral EO microsatellite, "
              "Argotec HEO platform with electric propulsion, SSO 500-600 km.",
              65.0, "ManualCorrection", "IRIDE HEO platform ~65 kg"),
    "64576": ("Electric_EP", "Electric propulsion (Argotec HEO platform)",
              "ManualCorrection", "High",
              "IRIDE-MS2-HEO-6: Italian IRIDE ~65 kg hyperspectral EO microsatellite, "
              "Argotec HEO platform with electric propulsion, SSO 500-600 km.",
              65.0, "ManualCorrection", "IRIDE HEO platform ~65 kg"),
    # Chemical
    "66645": ("Chemical", "Chemical bipropellant N2O4/MMH, Shenzhou spacecraft main engines + RCS",
              "ManualCorrection", "High",
              "SZ-22 (Shenzhou-22): Chinese crewed spacecraft docked to CSS. "
              "Chemical biprop N2O4/MMH, 4x2.5kN main engines + 24 RCS thrusters, ~1000 kg propellant. "
              "da=4.12km = CSS orbital maintenance burn.",
              7800.0, "ManualCorrection", "Shenzhou spacecraft ~7800 kg"),
    "54216": ("Chemical", "Chemical bipropellant propulsion (CSS Mengtian experiment module)",
              "ManualCorrection", "High",
              "CSS MENGTIAN: Chinese Space Station experiment module. "
              "Chemical biprop propulsion for station orbit maintenance. "
              "da=4.12km = CSS station orbit maintenance burn.",
              23000.0, "ManualCorrection", "CSS Mengtian module ~23000 kg"),
    "48274": ("Chemical", "Chemical bipropellant, 10kN main engine + RCS (CSS Tianhe core module)",
              "ManualCorrection", "High",
              "CSS TIANHE-1: Chinese Space Station core module. "
              "Chemical biprop, 10kN main engine + 4x2.5kN + RCS. "
              "da=4.12km = CSS station orbit maintenance burn.",
              22600.0, "ManualCorrection", "CSS Tianhe core ~22600 kg"),
    "66820": ("Chemical", "Chemical monopropellant thrusters for orbit maintenance",
              "ManualCorrection", "High",
              "KOMPSAT-7 (Korea Multi-Purpose Satellite 7): Korean optical EO ~800 kg. "
              "Chemical monoprop thrusters for orbit maintenance and maneuver.",
              800.0, "ManualCorrection", "KOMPSAT-7 ~800 kg"),
    "62673": ("Chemical", "Nitrous oxide green propellant, 8x Saiph thrusters, 176N total",
              "ManualCorrection", "High",
              "IMPULSE-2 MIRA: Impulse Space orbital transfer vehicle. "
              "8x Saiph thrusters on storable non-toxic N2O propellant, 176N total thrust. "
              "Historic 150km apogee raise as largest single N2O maneuver.",
              None, None, None),
    "53239": ("Chemical", "Chemical bipropellant propulsion (CSS Wentian experiment module)",
              "ManualCorrection", "High",
              "CSS WENTIAN: Chinese Space Station experiment module. "
              "Chemical biprop for station orbit maintenance. "
              "da=2.47km = CSS station orbit maintenance burn.",
              23200.0, "ManualCorrection", "CSS Wentian module ~23200 kg"),
    "56968": ("Chemical", "Chemical monopropellant thrusters for stationkeeping (Satellogic NuSat)",
              "ManualCorrection", "Medium",
              "NUSAT-43 R DIENG-KUNTZ: Satellogic 38.5 kg EO satellite. "
              "Chemical monoprop thrusters for limited stationkeeping. "
              "da=2.20km may reflect propellant depletion / drag-dominated decay.",
              38.5, "ManualCorrection", "Satellogic NuSat ~38.5 kg"),
    "46396": ("Chemical", "Chemical propulsion, onboard thrusters (Chinese optical reconnaissance)",
              "ManualCorrection", "High",
              "GAOFEN 11 2: Chinese high-resolution optical reconnaissance satellite. "
              "Chemical propulsion for orbit adjustment and maintenance. "
              "Exact thruster type not publicly disclosed.",
              None, None, None),
    # None (no propulsion)
    "66910": (NAN, NAN, "ManualCorrection", "High",
              "EAGLESAT-2: 3U CubeSat, US educational mission. "
              "No propulsion. da=4.82km from atmospheric drag at LEO.", None, None, None),
    "57326": (NAN, NAN, "ManualCorrection", "High",
              "STRATOSAT-TK1-D: 2TP TinySat, Russian educational. "
              "No propulsion. da=2.56km from atmospheric drag decay.", None, None, None),
    "47958": (NAN, NAN, "ManualCorrection", "High",
              "KMSL: 3U CubeSat, Korea Aerospace University. "
              "No propulsion. da=2.43km from atmospheric drag.", None, None, None),
    "58467": (NAN, NAN, "ManualCorrection", "High",
              "LILIUM-1: 3U CubeSat, NCKU Taiwan. "
              "No propulsion on first unit. da=2.18km from atmospheric drag.",
              4.0, "ManualCorrection", "Lilium-1 3U CubeSat ~4 kg"),
    "58319": (NAN, NAN, "ManualCorrection", "High",
              "FLOCK 4Q 15: Planet Labs Dove 3U CubeSat. "
              "No propulsion (standard Flock series). da=2.07km from atmospheric drag.", None, None, None),
    "44537": (NAN, NAN, "ManualCorrection", "High",
              "ZHUHAI-1 03C: Zhuhai Orbita early hyperspectral EO. "
              "No propulsion on early Zhuhai-1 series. da=1.91km from atmospheric drag.", None, None, None),
}


def apply(csv_path: str) -> None:
    try:
        df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"[SKIP] {csv_path} not found")
        return
    changed = skipped = 0
    for norad, (pc, pdesc, ps, pconf, pnote, mass, msrc, mnote) in PATCHES.items():
        mask = df["norad_id"].astype(str).str.strip() == norad
        if not mask.any():
            skipped += 1
            continue
        df.loc[mask, "propulsion_class"]       = pc
        df.loc[mask, "propulsion_description"] = pdesc
        df.loc[mask, "propulsion_source"]      = ps
        df.loc[mask, "propulsion_confidence"]  = pconf
        df.loc[mask, "propulsion_note"]        = pnote
        if mass is not None:
            df.loc[mask, "mass_kg"]     = str(mass)
            df.loc[mask, "mass_source"] = msrc
            df.loc[mask, "mass_note"]   = mnote
        changed += 1
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[OK] {csv_path}: {changed} updated, {skipped} not found")


if __name__ == "__main__":
    apply("output/annotations_leo_full.csv")
    apply("output/annotations_non_starlink_ucs.csv")
