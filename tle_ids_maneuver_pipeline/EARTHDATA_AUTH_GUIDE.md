# NASA Earthdata 認證設定 (CDDIS HTTPS)

## 1. 在 https://urs.earthdata.nasa.gov 申請帳號（免費）

## 2. 建立 ~/.netrc（Linux/macOS）或 ~/_netrc（Windows）

### Linux / macOS
```
cat >> ~/.netrc <<EOF
machine urs.earthdata.nasa.gov
login   YOUR_USERNAME
password YOUR_PASSWORD
EOF
chmod 600 ~/.netrc
```

### Windows (PowerShell)
```powershell
Add-Content "$env:USERPROFILE\_netrc" "machine urs.earthdata.nasa.gov`nlogin YOUR_USERNAME`npassword YOUR_PASSWORD"
```

## 3. 授權 CDDIS 應用程式（只需做一次）
  1. 登入 https://urs.earthdata.nasa.gov
  2. 進入 Applications > Authorized Apps
  3. 搜尋 "CDDIS" 並點 Authorize

## 4. 環境變數替代方案（CI/CD / Docker 適用）
```bash
export EARTHDATA_USERNAME=YOUR_USERNAME
export EARTHDATA_PASSWORD=YOUR_PASSWORD
```

## 5. 快速驗證
```bash
curl -n -c /tmp/cookies.txt -b /tmp/cookies.txt -L \
  "https://cddis.nasa.gov/archive/doris/products/orbits/ssa/ja3/" \
  | grep "ssaja3"
```

## 6. CDDIS 目錄結構（IDS SP3）
  https://cddis.nasa.gov/archive/doris/products/orbits/ssa/{sat_code}/
  檔名規則: ssasssVV.bXXDDD.eYYEEE.dgs.sp3.LLL.Z
  解碼:
    ssa = CNES/SSALTO analysis center
    sss = 3-char satellite code (ja3, s3a, cs2, ...)
    VV  = product version
    XXDDD = start year(2-digit) + DOY
    YYEEE = end   year(2-digit) + DOY
    dgs = data types used (D=DORIS, G=GPS, S=SLR)
    LLL = file replacement number
    .Z  = UNIX compress

## 7. 常見衛星代碼
  ja3 = Jason-3
  s3a = Sentinel-3A
  s3b = Sentinel-3B
  cs2 = CryoSat-2
  srl = SARAL
  s6a = Sentinel-6A
  h2a = HY-2A
  h2c = HY-2C
  h2d = HY-2D
  swt = SWOT
