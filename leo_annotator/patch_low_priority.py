"""Patch 29 low-priority FP satellites (da 1-2 km) based on user research report."""
import numpy as np
import pandas as pd

NAN = np.nan

PATCHES = {
    # Electric_EP
    "67383": ("Electric_EP", "Electric propulsion (Kepler Communications SmallSat platform)",
              "ManualCorrection", "High",
              "AETHER-12: Kepler Communications 300 kg optical data relay satellite. "
              "Electric propulsion for stationkeeping. 4+ optical terminals, SDA-compatible laser links.",
              300.0, "ManualCorrection", "Kepler AETHER-12 ~300 kg"),
    "57757": ("Electric_EP", "Krypton Hall-effect thruster (SpaceX Starlink bus)",
              "ManualCorrection", "High",
              "BB4: SDA Tranche 0 Tracking Layer OPIR satellite on SpaceX Starlink bus. "
              "Krypton Hall-effect thruster for orbit raising to ~1000 km, stationkeeping, deorbit.",
              None, None, None),
    "64571": ("Electric_EP", "Electric propulsion (Argotec HEO platform)",
              "ManualCorrection", "High",
              "IRIDE-MS2-HEO-5: Italian IRIDE ~65 kg hyperspectral EO microsatellite, "
              "Argotec HEO platform with electric propulsion, SSO 500-600 km.",
              65.0, "ManualCorrection", "IRIDE HEO platform ~65 kg"),
    "55049": ("Electric_EP", "ENPULSION IFM Nano FEEP thruster (indium liquid metal)",
              "ManualCorrection", "High",
              "ICEYE-X21: ICEYE X-band SAR satellite. "
              "ENPULSION IFM Nano FEEP (Field Emission Electric Propulsion) for precision orbit maintenance.",
              None, None, None),
    "63258": ("Electric_EP", "ENPULSION IFM Nano FEEP thruster",
              "ManualCorrection", "High",
              "ICEYE-X46: ICEYE X-band SAR satellite. "
              "ENPULSION IFM Nano FEEP for orbit maintenance and stationkeeping.",
              None, None, None),
    "66752": ("Electric_EP", "ENPULSION IFM Nano FEEP thruster",
              "ManualCorrection", "High",
              "ICEYE SAR-1: ICEYE X-band SAR satellite (Transporter-15, Nov 2025). "
              "ENPULSION IFM Nano FEEP for orbit maintenance.",
              None, None, None),
    # Micro/ColdGas
    "47517": ("Micro/ColdGas", "GomSpace Sweden cold gas thruster (butane propellant)",
              "ManualCorrection", "High",
              "ASTROCAST-0105: Astrocast 3U IoT CubeSat (2021). "
              "GomSpace Sweden cold gas butane propulsion for stationkeeping, CA, and deorbit. "
              "Operates at 500-600 km SSO.",
              None, None, None),
    # Chemical
    "60462": ("Chemical", "Chemical monopropellant thrusters (Chinese military LEO constellation)",
              "ManualCorrection", "High",
              "YAOGAN-43 O1E: Chinese military LEO constellation satellite, 500 km / 35 deg inclination. "
              "Chemical monoprop thrusters confirmed for formation phasing maneuvers.",
              None, None, None),
    "62757": ("Chemical", "Chemical propulsion (classified NRO reconnaissance satellite)",
              "ManualCorrection", "Low",
              "USA 486: NRO reconnaissance satellite (Falcon 9, Jan 2025, 43 deg LEO). "
              "Chemical propulsion inferred from active maneuver flags. Exact system classified.",
              None, None, None),
    "47231": ("Chemical", "Chemical monopropellant thrusters (Chinese large stereo mapping satellite)",
              "ManualCorrection", "High",
              "GAOFEN-14: Chinese large stereo mapping satellite ~500 kg (Dec 2020, CZ-3B, SSO). "
              "Chemical monoprop thrusters for orbit adjustment and maintenance.",
              500.0, "ManualCorrection", "Gaofen-14 ~500 kg"),
    "60949": ("Chemical", "Chemical monopropellant thrusters (Chinese military LEO constellation)",
              "ManualCorrection", "High",
              "YAOGAN-43 02E: Chinese military LEO constellation satellite (2nd batch, Sep 2024). "
              "Chemical monoprop thrusters for formation maintenance maneuvers.",
              None, None, None),
    "53316": ("Chemical", "Chemical monopropellant thrusters (Chinese military reconnaissance triplet)",
              "ManualCorrection", "High",
              "YAOGAN-35 03A: Chinese military reconnaissance triplet formation satellite. "
              "Chemical monoprop thrusters confirmed for orbit raising and formation phasing maneuvers.",
              None, None, None),
    # None (no propulsion)
    "43184": (NAN, NAN, "ManualCorrection", "High",
              "LEMUR-2 KADI: Spire Global 3U CubeSat (2018). "
              "No propulsion - early Spire LEMUR before ThrustMe I2T5 adoption (Q4 2022+). "
              "da=1.85km from atmospheric drag.",
              None, None, None),
    "61762": (NAN, NAN, "ManualCorrection", "High",
              "ARCTICSAT-1: 3U CubeSat, NARFU Russia, amateur radio (Nov 2024, Soyuz-2.1b). "
              "No propulsion - Geoscan 3U educational platform. da=1.70km from atmospheric drag.",
              None, None, None),
    "58272": (NAN, NAN, "ManualCorrection", "High",
              "TIGER-6: 6U CubeSat, OQ Technology Luxembourg, 5G NB-IoT (Nov 2023). "
              "No propulsion - Space Inventor 6U basic platform. da=1.45km from atmospheric drag.",
              None, None, None),
    "58313": (NAN, NAN, "ManualCorrection", "High",
              "FLOCK 4Q 20: Planet Labs SuperDove 3U CubeSat. "
              "No propulsion - uses differential drag for constellation phasing. da from drag.",
              None, None, None),
    "61440": (NAN, NAN, "ManualCorrection", "High",
              "H-2A R/B: Japanese H-2A rocket body debris (Sep 2024, ALOS-4 mission). "
              "No propulsion - passive rocket body. da=1.34km from atmospheric drag decay.",
              None, None, None),
    "39472": (NAN, NAN, "ManualCorrection", "High",
              "SMDC ONE 2.4: 3U CubeSat, US Army SMDC, comms experiment (2013). "
              "No propulsion - SMDC-ONE basic design; propulsion added only in later SNaP series. "
              "da=1.12km from atmospheric drag.",
              None, None, None),
    "58329": (NAN, NAN, "ManualCorrection", "High",
              "FLOCK 4Q 21: Planet Labs SuperDove 3U CubeSat. "
              "No propulsion - differential drag control. da from drag.",
              None, None, None),
    "44495": (NAN, NAN, "ManualCorrection", "High",
              "BRO-1: 6U CubeSat, Unseenlabs/GomSpace France, maritime RF intelligence (first unit). "
              "No confirmed propulsion on BRO-1 - propulsion is optional on GomSpace 6U, not installed. "
              "da=1.05km from atmospheric drag.",
              None, None, None),
    "56185": (NAN, NAN, "ManualCorrection", "High",
              "BRO-9: 6U CubeSat, Unseenlabs/GomSpace France, maritime RF intelligence. "
              "No confirmed propulsion on BRO 1-11 series. da=1.04km from atmospheric drag.",
              None, None, None),
    "60558": (NAN, NAN, "ManualCorrection", "High",
              "FLOCK 4BE 35: Planet Labs SuperDove 3U CubeSat (Transporter-11, Aug 2024). "
              "No propulsion - differential drag control. da from drag.",
              None, None, None),
    "60484": (NAN, NAN, "ManualCorrection", "High",
              "FLOCK 4BE 26: Planet Labs SuperDove 3U CubeSat (Transporter-11, Aug 2024). "
              "No propulsion - differential drag control. da from drag.",
              None, None, None),
    "46818": (NAN, NAN, "ManualCorrection", "High",
              "CE-SAT IIB: 35.5 kg EO microsatellite, Canon Electronics Japan (Oct 2020, Electron, SSO 500 km). "
              "No propulsion - attitude control by reaction wheels and magnetorquers only. "
              "da=1.00km from atmospheric drag.",
              None, None, None),
    "66912": (NAN, NAN, "ManualCorrection", "High",
              "CONTENTCUBE: 1U CubeSat, Cal Poly Pomona, display experiment (deployed from ISS, 2025). "
              "No propulsion. da=1.14km from atmospheric drag.",
              None, None, None),
    "62643": (NAN, NAN, "ManualCorrection", "High",
              "FLOCK 4G 32: Planet Labs SuperDove 3U CubeSat (Jan 2025). "
              "No propulsion - differential drag control. da from drag.",
              None, None, None),
    "41340": (NAN, NAN, "ManualCorrection", "High",
              "HORYU-4: 10-12 kg tech demo, Kyushu Institute of Technology (2016, H-2A). "
              "Vacuum arc thruster carried as EXPERIMENT PAYLOAD only, not main propulsion. "
              "Primary orbit decay is atmospheric drag. da=1.14km from drag.",
              None, None, None),
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
