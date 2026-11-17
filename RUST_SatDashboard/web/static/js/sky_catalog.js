'use strict';
/* 天球圖恆星表：21 顆一等星（視星等 ≤ 1.5 之傳統一等星）＋北極星（定向參考）。
   座標（J2000，RA 時／Dec 度）與視星等、B-V 取自 d3-celestial（ofrohn/d3-celestial, BSD-3-Clause）
   之 stars.6.json（Hipparcos），授權全文見 vendor/celestial/LICENSE-d3-celestial.txt。 */
window.SKY_STARS=[
  {hip:32349,ra:6.7525,dec:-16.7161,mag:-1.44,bv:0.009,n:{zh:'天狼星',ja:'シリウス',en:'Sirius'}},
  {hip:30438,ra:6.3992,dec:-52.6957,mag:-0.62,bv:0.164,n:{zh:'老人星',ja:'カノープス',en:'Canopus'}},
  {hip:69673,ra:14.2610,dec:19.1824,mag:-0.05,bv:1.239,n:{zh:'大角星',ja:'アルクトゥルス',en:'Arcturus'}},
  {hip:71683,ra:14.6601,dec:-60.8340,mag:-0.01,bv:0.710,n:{zh:'南門二',ja:'リギル・ケンタウルス',en:'Rigil Kentaurus'}},
  {hip:91262,ra:18.6156,dec:38.7837,mag:0.03,bv:-0.001,n:{zh:'織女星',ja:'ベガ',en:'Vega'}},
  {hip:24608,ra:5.2782,dec:45.9980,mag:0.08,bv:0.795,n:{zh:'五車二',ja:'カペラ',en:'Capella'}},
  {hip:24436,ra:5.2423,dec:-8.2016,mag:0.18,bv:-0.030,n:{zh:'參宿七',ja:'リゲル',en:'Rigel'}},
  {hip:37279,ra:7.6550,dec:5.2250,mag:0.40,bv:0.432,n:{zh:'南河三',ja:'プロキオン',en:'Procyon'}},
  {hip:7588,ra:1.6286,dec:-57.2368,mag:0.45,bv:-0.158,n:{zh:'水委一',ja:'アケルナル',en:'Achernar'}},
  {hip:27989,ra:5.9195,dec:7.4071,mag:0.45,bv:1.500,n:{zh:'參宿四',ja:'ベテルギウス',en:'Betelgeuse'}},
  {hip:68702,ra:14.0637,dec:-60.3730,mag:0.61,bv:-0.231,n:{zh:'馬腹一',ja:'ハダル',en:'Hadar'}},
  {hip:97649,ra:19.8464,dec:8.8683,mag:0.76,bv:0.221,n:{zh:'牛郎星',ja:'アルタイル',en:'Altair'}},
  {hip:60718,ra:12.4433,dec:-63.0991,mag:0.77,bv:-0.243,n:{zh:'十字架二',ja:'アクルックス',en:'Acrux'}},
  {hip:21421,ra:4.5987,dec:16.5093,mag:0.87,bv:1.538,n:{zh:'畢宿五',ja:'アルデバラン',en:'Aldebaran'}},
  {hip:65474,ra:13.4199,dec:-11.1613,mag:0.98,bv:-0.235,n:{zh:'角宿一',ja:'スピカ',en:'Spica'}},
  {hip:80763,ra:16.4901,dec:-26.4320,mag:1.06,bv:1.865,n:{zh:'心宿二',ja:'アンタレス',en:'Antares'}},
  {hip:37826,ra:7.7553,dec:28.0262,mag:1.16,bv:0.991,n:{zh:'北河三',ja:'ポルックス',en:'Pollux'}},
  {hip:113368,ra:22.9608,dec:-29.6222,mag:1.17,bv:0.145,n:{zh:'北落師門',ja:'フォーマルハウト',en:'Fomalhaut'}},
  {hip:102098,ra:20.6905,dec:45.2803,mag:1.25,bv:0.092,n:{zh:'天津四',ja:'デネブ',en:'Deneb'}},
  {hip:62434,ra:12.7954,dec:-59.6888,mag:1.25,bv:-0.238,n:{zh:'十字架三',ja:'ミモザ',en:'Mimosa'}},
  {hip:49669,ra:10.1395,dec:11.9672,mag:1.36,bv:-0.087,n:{zh:'軒轅十四',ja:'レグルス',en:'Regulus'}},
  {hip:11767,ra:2.5303,dec:89.2641,mag:1.97,bv:0.636,n:{zh:'北極星',ja:'ポラリス',en:'Polaris'}},
];
