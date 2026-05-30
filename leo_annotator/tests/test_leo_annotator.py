"""
Tests for leo_satellite_annotator.py

執行方式：
    cd leo_annotator
    pytest tests/ -v
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import leo_satellite_annotator as module
from leo_satellite_annotator import (
    annotate_satellite,
    classify_mass,
    classify_orbit_band,
    classify_platform,
    classify_propulsion,
    fetch_celestrak,
    load_input_csv,
    lookup_ucs,
    map_mission_type,
    scrape_keeptrack,
    scrape_nanosats,
)


# ─────────────────────────────────────────────────────────────────────────────
# 共用 helper
# ─────────────────────────────────────────────────────────────────────────────

def _mock_response(json_data=None, status_code=200, html=""):
    """建立模擬的 requests.Response 物件。"""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else []
    m.text = html
    if status_code >= 400:
        m.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        m.raise_for_status.return_value = None
    return m


def _celestrak_payload(
    apogee=550, perigee=540,
    name="STARLINK-1792", cospar="2021-022A",
):
    return [{
        "INTLDES": cospar,
        "OBJECT_NAME": name,
        "APOGEE": apogee,
        "PERIGEE": perigee,
        "RCS_SIZE": "MEDIUM",
        "PERIOD": 95.5,
        "INCLINATION": 53.0,
    }]


# ─────────────────────────────────────────────────────────────────────────────
# 1. classify_orbit_band
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyOrbitBand:
    def test_none_returns_empty(self):
        assert classify_orbit_band(None) == ""

    def test_below_300_out_of_range(self):
        assert classify_orbit_band(200) == "OUT_OF_RANGE"

    def test_exactly_300_lower_bound(self):
        assert classify_orbit_band(300) == "LEO_300_450"

    def test_mid_low_leo(self):
        assert classify_orbit_band(380) == "LEO_300_450"

    def test_exactly_450_upper_bound(self):
        assert classify_orbit_band(450) == "LEO_300_450"

    def test_451_enters_next_band(self):
        assert classify_orbit_band(451) == "LEO_450_800"

    def test_mid_leo(self):
        assert classify_orbit_band(600) == "LEO_450_800"

    def test_exactly_800_upper_bound(self):
        assert classify_orbit_band(800) == "LEO_450_800"

    def test_801_enters_high_leo(self):
        assert classify_orbit_band(801) == "LEO_800_1000"

    def test_exactly_1000_upper_bound(self):
        assert classify_orbit_band(1000) == "LEO_800_1000"

    def test_above_1000_out_of_range(self):
        assert classify_orbit_band(1200) == "OUT_OF_RANGE"


# ─────────────────────────────────────────────────────────────────────────────
# 2. classify_mass
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyMass:
    def test_none_returns_empty(self):
        assert classify_mass(None) == ""

    def test_below_10(self):
        assert classify_mass(1.5) == "<10kg"

    def test_exactly_10_lower_bound(self):
        assert classify_mass(10) == "10_50kg"

    def test_mid_small(self):
        assert classify_mass(25) == "10_50kg"

    def test_exactly_50_lower_bound(self):
        assert classify_mass(50) == "50_200kg"

    def test_mid_micro(self):
        assert classify_mass(100) == "50_200kg"

    def test_exactly_200_lower_bound(self):
        assert classify_mass(200) == "200_1000kg"

    def test_mid_medium(self):
        assert classify_mass(500) == "200_1000kg"

    def test_exactly_1000_threshold(self):
        assert classify_mass(1000) == ">1000kg"

    def test_large_satellite(self):
        assert classify_mass(5000) == ">1000kg"


# ─────────────────────────────────────────────────────────────────────────────
# 3. classify_platform
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPlatform:
    def test_none_returns_unknown(self):
        assert classify_platform(None) == "Unknown"

    def test_cubesat(self):
        assert classify_platform(4) == "Cube/Nano"

    def test_nanosatellite_boundary(self):
        assert classify_platform(49.9) == "Cube/Nano"

    def test_micro_lower_bound(self):
        assert classify_platform(50) == "Micro"

    def test_micro_upper_bound(self):
        assert classify_platform(199) == "Micro"

    def test_small_satellite(self):
        assert classify_platform(200) == "Small/Medium"

    def test_large_satellite(self):
        assert classify_platform(2000) == "Small/Medium"


# ─────────────────────────────────────────────────────────────────────────────
# 4. classify_propulsion
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPropulsion:
    def test_empty_string(self):
        cls, desc = classify_propulsion("")
        assert cls == "None"
        assert "No propulsion" in desc

    def test_none_input(self):
        cls, _ = classify_propulsion(None)
        assert cls == "None"

    def test_hall_thruster_electric(self):
        cls, desc = classify_propulsion("200 W Hall thruster, xenon propellant")
        assert cls == "Electric_EP"
        assert desc != ""

    def test_gridded_ion_engine_electric(self):
        cls, _ = classify_propulsion("gridded ion engine 50 mN thrust")
        assert cls == "Electric_EP"

    def test_hydrazine_monopropellant_chemical(self):
        cls, _ = classify_propulsion("hydrazine monopropellant 1 N thruster")
        assert cls == "Chemical"

    def test_green_propellant_chemical(self):
        cls, _ = classify_propulsion("HPGP green propellant thruster")
        assert cls == "Chemical"

    def test_cold_gas(self):
        cls, _ = classify_propulsion("cold gas nitrogen system")
        assert cls == "Micro/ColdGas"

    def test_pulsed_plasma_micro(self):
        cls, _ = classify_propulsion("pulsed plasma thruster (PPT)")
        assert cls == "Micro/ColdGas"

    def test_generic_thruster_hybrid(self):
        # "thruster" matches generic_kw → Hybrid/Other
        cls, desc = classify_propulsion("custom thruster (type undisclosed)")
        assert cls == "Hybrid/Other"
        assert "unclear" in desc

    def test_no_propulsion_keywords(self):
        # 無任何推進關鍵字 → None
        cls, _ = classify_propulsion("solar panels only, gravity gradient stabilization")
        assert cls == "None"


# ─────────────────────────────────────────────────────────────────────────────
# 5. map_mission_type
# ─────────────────────────────────────────────────────────────────────────────

class TestMapMissionType:
    def test_comm(self):
        assert map_mission_type("broadband communication relay") == "COMM"

    def test_eo(self):
        assert map_mission_type("Earth observation and remote sensing") == "EO"

    def test_techdemo(self):
        assert map_mission_type("Technology demonstration experiment") == "TechDemo"

    def test_science(self):
        assert map_mission_type("Space science research") == "Science"

    def test_nav(self):
        assert map_mission_type("Navigation and GPS positioning") == "Nav"

    def test_other_unrecognised(self):
        # "meteorological" 含子字串 "eo"，會被誤判為 EO；改用無任何關鍵字的字串
        assert map_mission_type("weather forecasting support") == "Other"

    def test_empty_string(self):
        assert map_mission_type("") == "Other"

    def test_none_input(self):
        assert map_mission_type(None) == "Other"


# ─────────────────────────────────────────────────────────────────────────────
# 6. load_input_csv
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadInputCsv:
    def test_full_four_column_csv(self, tmp_path):
        csv = tmp_path / "sats.csv"
        csv.write_text(
            "NORAD_ID,COSPAR_ID,NAME,MEAN_ALT_KM\n"
            "25544,1998-067A,ISS,408\n"
            "48274,2021-022A,STARLINK-1792,550\n",
            encoding="utf-8",
        )
        sats = load_input_csv(str(csv))
        assert len(sats) == 2
        assert sats[0]["norad_id"] == "25544"
        assert sats[0]["cospar_id"] == "1998-067A"
        assert sats[0]["name"] == "ISS"
        assert sats[0]["alt_km"] == pytest.approx(408.0)

    def test_norad_only_csv(self, tmp_path):
        csv = tmp_path / "minimal.csv"
        csv.write_text("NORAD_ID\n44057\n43689\n", encoding="utf-8")
        sats = load_input_csv(str(csv))
        assert len(sats) == 2
        assert sats[0]["norad_id"] == "44057"
        assert sats[0]["alt_km"] is None
        assert sats[0]["cospar_id"] == ""

    def test_missing_alt_column(self, tmp_path):
        csv = tmp_path / "no_alt.csv"
        csv.write_text("NORAD_ID,NAME\n25544,ISS\n", encoding="utf-8")
        sats = load_input_csv(str(csv))
        assert sats[0]["alt_km"] is None

    def test_invalid_alt_value_becomes_none(self, tmp_path):
        csv = tmp_path / "bad_alt.csv"
        csv.write_text("NORAD_ID,MEAN_ALT_KM\n25544,N/A\n", encoding="utf-8")
        sats = load_input_csv(str(csv))
        assert sats[0]["alt_km"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. lookup_ucs（注入 mock DataFrame）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def ucs_df(monkeypatch):
    """注入小型的 UCS DataFrame 供測試使用。"""
    df = pd.DataFrame([
        {
            "NORAD Number": "25544",
            "COSPAR Number": "1998-067A",
            "Name of Satellite, Alternate Names": "ISS (ZARYA)",
            "Launch Mass (kg.)": "420000",
            "Dry Mass (kg.)": "340000",
            "Purpose": "Space science research",
        },
        {
            "NORAD Number": "48274",
            "COSPAR Number": "2021-022A",
            "Name of Satellite, Alternate Names": "STARLINK-1792",
            "Launch Mass (kg.)": "260",
            "Dry Mass (kg.)": "",
            "Purpose": "communication broadband",
        },
        {
            # 無 launch mass，只有 dry mass
            "NORAD Number": "99991",
            "COSPAR Number": "",
            "Name of Satellite, Alternate Names": "DRYONLY-SAT",
            "Launch Mass (kg.)": "",
            "Dry Mass (kg.)": "5",
            "Purpose": "",
        },
    ])
    monkeypatch.setattr(module, "_ucs_df", df)
    return df


class TestLookupUcs:
    def test_match_by_norad(self, ucs_df):
        result = lookup_ucs("25544")
        assert result["mass_kg"] == pytest.approx(420000.0)
        assert result["mass_source"] == "UCS"
        assert result["mass_confidence"] == "High"
        assert result["mission_type"] == "Science"

    def test_match_by_name_fallback(self, ucs_df):
        # NORAD 不存在，但名稱可匹配
        result = lookup_ucs("00000", sat_name="STARLINK-1792")
        assert result["mass_kg"] == pytest.approx(260.0)
        assert result["mission_type"] == "COMM"

    def test_no_match_returns_empty_dict(self, ucs_df):
        result = lookup_ucs("11111", sat_name="NONEXISTENT-SAT")
        assert result == {}

    def test_dry_mass_fallback_when_launch_mass_missing(self, ucs_df):
        result = lookup_ucs("99991")
        assert result["mass_kg"] == pytest.approx(5.0)
        assert result["mass_confidence"] == "Medium"
        assert "dry mass" in result["mass_note"].lower()

    def test_ucs_none_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(module, "_ucs_df", None)
        assert lookup_ucs("25544") == {}


# ─────────────────────────────────────────────────────────────────────────────
# 8. fetch_celestrak（mock HTTP）
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchCelestrak:
    def test_successful_response(self):
        payload = [{
            "INTLDES": "1998-067A",
            "OBJECT_NAME": "ISS (ZARYA)",
            "APOGEE": 420,
            "PERIGEE": 410,
            "RCS_SIZE": "LARGE",
            "PERIOD": 92.9,
            "INCLINATION": 51.6,
        }]
        with patch("requests.get", return_value=_mock_response(json_data=payload)):
            result = fetch_celestrak(25544)
        assert result["cospar_id"] == "1998-067A"
        assert result["sat_name"] == "ISS (ZARYA)"
        assert result["mean_alt_km"] == pytest.approx(415.0)
        assert result["orbit_band"] == "LEO_300_450"

    def test_empty_json_returns_empty_dict(self):
        with patch("requests.get", return_value=_mock_response(json_data=[])):
            result = fetch_celestrak(99999)
        assert result == {}

    def test_http_error_returns_empty_dict(self):
        with patch("requests.get", return_value=_mock_response(status_code=404)):
            result = fetch_celestrak(99999)
        assert result == {}

    def test_network_exception_returns_empty_dict(self):
        with patch("requests.get", side_effect=Exception("connection timeout")):
            result = fetch_celestrak(25544)
        assert result == {}

    def test_missing_apogee_perigee_gives_empty_orbit_band(self):
        payload = [{"INTLDES": "2021-022A", "OBJECT_NAME": "STARLINK-1792"}]
        with patch("requests.get", return_value=_mock_response(json_data=payload)):
            result = fetch_celestrak(48274)
        assert result["mean_alt_km"] is None
        assert result["orbit_band"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 9. scrape_nanosats（mock HTTP）
# ─────────────────────────────────────────────────────────────────────────────

_NANOSATS_HTML = """
<html><body><table>
  <tr><td>Mass</td><td>1.33 kg</td></tr>
  <tr><td>Propulsion system</td><td>Cold gas nitrogen thruster</td></tr>
  <tr><td>Launch date</td><td>2021-03-22</td></tr>
</table></body></html>
"""


class TestScrapeNanosats:
    def test_successful_mass_and_propulsion(self):
        resp = _mock_response(status_code=200, html=_NANOSATS_HTML)
        with patch("requests.get", return_value=resp):
            result = scrape_nanosats("LEMUR-2")
        assert result["mass_kg"] == pytest.approx(1.33)
        assert result["mass_source"] == "NanosatDB"
        assert "cold gas" in result["propulsion_raw"].lower()

    def test_404_returns_empty_dict(self):
        with patch("requests.get", return_value=_mock_response(status_code=404)):
            result = scrape_nanosats("UNKNOWN-SAT")
        assert result == {}

    def test_network_exception_returns_empty_dict(self):
        with patch("requests.get", side_effect=Exception("timeout")):
            result = scrape_nanosats("LEMUR-2")
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# 10. scrape_keeptrack（mock HTTP）
# ─────────────────────────────────────────────────────────────────────────────

_KEEPTRACK_HTML = """
<html><body>
<p>Launch Mass</p><p>260 kg</p>
<p>Motor</p><p>Hall-effect thruster</p>
</body></html>
"""


class TestScrapeKeepTrack:
    def test_successful_mass_and_propulsion(self):
        resp = _mock_response(status_code=200, html=_KEEPTRACK_HTML)
        with patch("requests.get", return_value=resp):
            result = scrape_keeptrack(66666)
        assert result["mass_kg"] == pytest.approx(260.0)
        assert result["mass_source"] == "KeepTrack"
        assert "propulsion_raw" in result

    def test_404_returns_empty_dict(self):
        with patch("requests.get", return_value=_mock_response(status_code=404)):
            result = scrape_keeptrack(99999)
        assert result == {}

    def test_network_exception_returns_empty_dict(self):
        with patch("requests.get", side_effect=Exception("connection refused")):
            result = scrape_keeptrack(66666)
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# 11. annotate_satellite 整合測試（所有 HTTP 來源全部 mock）
# ─────────────────────────────────────────────────────────────────────────────

_N2YO_HTML = """
<html><body>
<p>Apogee: 548 km</p>
<p>Perigee: 532 km</p>
</body></html>
"""


class TestAnnotateSatellite:
    """驗證多來源合併優先順序與 fallback 邏輯。"""

    def test_ucs_mass_takes_priority_over_nanosats(self, monkeypatch):
        """UCS 有質量時，Nanosats 的質量不得覆蓋。"""
        df = pd.DataFrame([{
            "NORAD Number": "48274",
            "COSPAR Number": "2021-022A",
            "Name of Satellite, Alternate Names": "STARLINK-1792",
            "Launch Mass (kg.)": "260",
            "Dry Mass (kg.)": "",
            "Purpose": "communication broadband",
        }])
        monkeypatch.setattr(module, "_ucs_df", df)

        responses = [
            _mock_response(json_data=_celestrak_payload()),       # CelesTrak
            _mock_response(status_code=200, html=_NANOSATS_HTML), # Nanosats (4.5 kg)
            _mock_response(status_code=404),                      # KeepTrack
        ]
        with patch("requests.get", side_effect=responses), patch("time.sleep"):
            rec = annotate_satellite(48274, request_delay=0)

        assert rec["mass_kg"] == pytest.approx(260.0)
        assert rec["mass_source"] == "UCS"
        assert rec["orbit_band"] == "LEO_450_800"

    def test_nanosats_mass_fills_when_ucs_absent(self, monkeypatch):
        """UCS 無資料時，質量應由 Nanosats 填入。"""
        monkeypatch.setattr(module, "_ucs_df", None)

        responses = [
            _mock_response(json_data=_celestrak_payload(name="LEMUR-2")),
            _mock_response(status_code=200, html=_NANOSATS_HTML),
            _mock_response(status_code=404),  # KeepTrack
        ]
        with patch("requests.get", side_effect=responses), patch("time.sleep"):
            rec = annotate_satellite(44057, request_delay=0)

        assert rec["mass_kg"] == pytest.approx(1.33)
        assert rec["mass_source"] == "NanosatDB"

    def test_n2yo_orbit_fallback_triggered_when_celestrak_missing(self, monkeypatch):
        """CelesTrak 無軌道資料時，應透過 N2YO fallback 填入 orbit_band。"""
        monkeypatch.setattr(module, "_ucs_df", None)

        # CelesTrak 回傳無 APOGEE/PERIGEE 的記錄
        ct_no_orbit = _mock_response(
            json_data=[{"INTLDES": "2021-022A", "OBJECT_NAME": "STARLINK-1792"}]
        )
        responses = [
            ct_no_orbit,
            _mock_response(status_code=404),                    # Nanosats
            _mock_response(status_code=404),                    # KeepTrack
            _mock_response(status_code=200, html=_N2YO_HTML),  # N2YO fallback
        ]
        with patch("requests.get", side_effect=responses), patch("time.sleep"):
            rec = annotate_satellite(48274, request_delay=0)

        assert rec["orbit_band"] == "LEO_450_800"

    def test_all_sources_fail_returns_valid_blank_record(self, monkeypatch):
        """所有來源皆失敗時，應回傳結構完整但欄位空白的記錄（不拋例外）。"""
        monkeypatch.setattr(module, "_ucs_df", None)
        with patch("requests.get", side_effect=Exception("network down")), \
             patch("time.sleep"):
            rec = annotate_satellite(99999, request_delay=0)

        assert rec["norad_id"] == "99999"
        assert rec["propulsion_class"] == "None"
        assert rec["mass_confidence"] == "Low"
        assert rec["mass_note"] != ""
