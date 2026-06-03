# TLE vs IDS Maneuver Detection Pipeline

This project builds a practical pipeline to compare a local TLE archive against IDS precise orbit products and detect likely orbit maneuvers.

## Data sources
- ILRS maneuver page: https://ilrs.gsfc.nasa.gov/data_and_products/predictions/maneuver.html
- ILRS satellite names page: https://ilrs.gsfc.nasa.gov/missions/satellite_names.html
- IDS orbit products at CDDIS: https://cddis.nasa.gov/archive/doris/products/orbits/ssa/

## Supported mission codes
According to the IDS orbit product description, common satellite codes include:
- cs2 = Cryosat-2
- en1 = Envisat-1
- h2a = HY-2A
- ja1 = Jason-1
- ja2 = Jason-2
- ja3 = Jason-3
- s3a = Sentinel-3A
- s3b = Sentinel-3B
- srl = SARAL
- top = TOPEX/Poseidon

## Repository structure
- config.yaml
- ingest_ilrs.py
- download_ids.py
- tle_db.py
- propagate_tle.py
- compare_residuals.py
- detect_maneuver.py
- run_pipeline.py
- utils.py

## Install
```bash
pip install requests beautifulsoup4 pandas numpy scipy pyyaml sgp4 astropy lxml
```

For authenticated CDDIS access, set:
```bash
export EARTHDATA_USERNAME=your_user
export EARTHDATA_PASSWORD=your_password
```

## Minimal run
```bash
python run_pipeline.py --config config.yaml --satellite jason-3
```
