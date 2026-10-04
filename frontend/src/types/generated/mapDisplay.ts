// 生成物。`backend/scripts/export_openapi.py`が書き出す。手で編集しない。
export const mapDisplay = {
  "overlayGroups": [
    {
      "key": "road",
      "label": "道路"
    },
    {
      "key": "environment",
      "label": "環境"
    },
    {
      "key": "spot",
      "label": "スポット"
    }
  ],
  "legendSharedRows": {
    "other": {
      "label": "その他",
      "description": "値は書かれているが、上のどの行にも当てはまらない道（まれな種類など）。"
    },
    "notApplicable": {
      "label": "該当なし",
      "description": "この種類に当たらない道（例: トンネルの凡例では、トンネルでない道）。"
    },
    "noData": {
      "label": "データなし",
      "description": "元にする地図のデータに値が無く、どの行にも分けられない道。道が無いのではなく、値が分からないことを破線で示す。"
    }
  },
  "layerCategories": [
    {
      "key": "roadCondition",
      "group": "road"
    },
    {
      "key": "terrain",
      "group": "environment"
    },
    {
      "key": "weather",
      "group": "environment"
    },
    {
      "key": "disaster",
      "group": "environment"
    },
    {
      "key": "trafficSafety",
      "group": "spot"
    },
    {
      "key": "amenity",
      "group": "spot"
    }
  ],
  "layerDataSources": [
    {
      "key": "road_surface",
      "minZoom": 12
    },
    {
      "key": "poi",
      "minZoom": 12
    },
    {
      "key": "accident",
      "minZoom": 12
    },
    {
      "key": "gsiRelief",
      "minZoom": null
    },
    {
      "key": "gsiTerrain",
      "minZoom": 2
    },
    {
      "key": "landcoverRaster",
      "minZoom": 6
    },
    {
      "key": "ownFetch",
      "minZoom": null
    }
  ],
  "layerDataNatures": [
    "raw",
    "composite",
    "dynamic"
  ],
  "layerKinds": [
    "static",
    "dynamic"
  ],
  "layers": [
    {
      "id": "highway",
      "label": "道路の種類",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "surface",
      "label": "路面の種類",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "tracktype",
      "label": "農道・林道の等級",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "tunnel",
      "label": "トンネル",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "oneway",
      "label": "一方通行",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "elevation",
      "label": "標高図",
      "dataSource": "gsiRelief",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "stop_poi",
      "label": "停止要因",
      "dataSource": "poi",
      "category": "trafficSafety",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "accident_point",
      "label": "事故[警察庁統計]",
      "dataSource": "accident",
      "category": "trafficSafety",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "landcover",
      "label": "緑と水",
      "dataSource": "landcoverRaster",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "supply_poi",
      "label": "補給・休憩ポイント",
      "dataSource": "poi",
      "category": "amenity",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "hillshade",
      "label": "起伏",
      "dataSource": "gsiTerrain",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "precipitationNowcast",
      "label": "降水ナウキャスト",
      "dataSource": "ownFetch",
      "category": "weather",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false
    },
    {
      "id": "windVector",
      "label": "風[矢印]",
      "dataSource": "ownFetch",
      "category": "weather",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false
    },
    {
      "id": "disaster",
      "label": "災害",
      "dataSource": "ownFetch",
      "category": "disaster",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": true
    },
    {
      "id": "route",
      "label": "ルート",
      "dataSource": "ownFetch",
      "category": null,
      "kind": "dynamic",
      "dataNature": "raw",
      "defaultOn": true
    }
  ],
  "axisLayers": {
    "ramp": {
      "dataSource": "road_surface",
      "category": null,
      "kind": "static",
      "dataNature": "composite",
      "defaultOn": false
    },
    "dedicated": {
      "dataSource": "road_surface",
      "category": null,
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false
    }
  },
  "weatherLayerGroups": [
    "precipitationNowcast",
    "windVector",
    "disaster"
  ],
  "weatherElements": [
    {
      "group": "precipitationNowcast",
      "source": "main",
      "kind": "rasterTile",
      "label": "降水",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": null,
      "description": null,
      "jmaElements": [
        {
          "id": "hrpns",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N1.json",
            "bosai/jmatile/data/nowc/targetTimes_N2.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/hrpns/{z}/{x}/{y}.png",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 0
        },
        {
          "id": "rasrf",
          "targetTimesPaths": [
            "bosai/jmatile/data/rasrf/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/rasrf/{basetime}/{member}/{validtime}/surf/rasrf/{z}/{x}/{y}.png",
          "reader": "latestFullRun",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": null
      }
    },
    {
      "group": "precipitationNowcast",
      "source": "main",
      "kind": "gridFill",
      "label": "降水",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": "precipitation",
      "levelScale": null,
      "description": null,
      "jmaElements": [],
      "tile": null
    },
    {
      "group": "precipitationNowcast",
      "source": "linearRainband",
      "kind": "rasterTile",
      "label": "線状降水帯予測",
      "frameRule": {
        "kind": "current",
        "windowMinutes": 180
      },
      "gridValue": null,
      "levelScale": null,
      "description": null,
      "jmaElements": [
        {
          "id": "sjfcstmap",
          "targetTimesPaths": [
            "bosai/jmatile/data/rasrf/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/rasrf/{basetime}/{member}/{validtime}/surf/sjfcstmap/{z}/{x}/{y}.png",
          "reader": "latest",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": null
      }
    },
    {
      "group": "precipitationNowcast",
      "source": "linearRainbandArea",
      "kind": "outline",
      "label": "線状降水帯の雨域",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": null,
      "description": null,
      "jmaElements": [
        {
          "id": "slmcs_unify",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/slmcs_unify/data.geojson?id=slmcs_unify",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 10
        }
      ],
      "tile": null
    },
    {
      "group": "precipitationNowcast",
      "source": "linearRainbandAreaForecast",
      "kind": "outline",
      "label": "線状降水帯の雨域",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": null,
      "description": null,
      "jmaElements": [
        {
          "id": "slmcs_unifyfcst",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/slmcs_unifyfcst/data.geojson?id=slmcs_unifyfcst",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 10
        }
      ],
      "tile": null
    },
    {
      "group": "windVector",
      "source": "arrow",
      "kind": "gridMark",
      "label": "風",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": "wind",
      "levelScale": null,
      "description": null,
      "jmaElements": [],
      "tile": null
    },
    {
      "group": "disaster",
      "source": "heavyRain",
      "kind": "rasterTile",
      "label": "大雨キキクル",
      "frameRule": {
        "kind": "current",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": "risk_levels",
      "description": "大雨による土砂災害と浸水害の危険度の高まりを、まとめて段階で示す気象庁の情報。",
      "jmaElements": [
        {
          "id": "rain_mesh",
          "targetTimesPaths": [
            "bosai/jmatile/data/risk/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/rain_mesh/{z}/{x}/{y}.png",
          "reader": "latest",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": null
      }
    },
    {
      "group": "disaster",
      "source": "landslide",
      "kind": "rasterTile",
      "label": "土砂災害キキクル",
      "frameRule": {
        "kind": "current",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": "risk_levels",
      "description": "大雨による土砂災害（がけ崩れ・土石流など）の危険度の高まりを段階で示す気象庁の情報。",
      "jmaElements": [
        {
          "id": "land",
          "targetTimesPaths": [
            "bosai/jmatile/data/risk/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/land/{z}/{x}/{y}.png",
          "reader": "latest",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": null
      }
    },
    {
      "group": "disaster",
      "source": "inundation",
      "kind": "rasterTile",
      "label": "浸水キキクル",
      "frameRule": {
        "kind": "current",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": "risk_levels",
      "description": "短い時間の強い雨で、道路や低い土地が水につかる危険度の高まりを段階で示す気象庁の情報。",
      "jmaElements": [
        {
          "id": "inund",
          "targetTimesPaths": [
            "bosai/jmatile/data/risk/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/inund/{z}/{x}/{y}.png",
          "reader": "latest",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": null
      }
    },
    {
      "group": "disaster",
      "source": "thunder",
      "kind": "rasterTile",
      "label": "雷ナウキャスト",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": "thunder_activity",
      "description": "雷の激しさと雷が起こる可能性を、活動度の段階で示す気象庁の実況と1時間先までの予測。",
      "jmaElements": [
        {
          "id": "thns",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/thns/{z}/{x}/{y}.png",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 8,
        "vectorLayer": null
      }
    },
    {
      "group": "disaster",
      "source": "tornado",
      "kind": "rasterTile",
      "label": "竜巻発生確度",
      "frameRule": {
        "kind": "nearest",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": "tornado_potential",
      "description": "竜巻などの激しい突風が起こりやすい所を、確度の段階で示す気象庁の実況と1時間先までの予測。",
      "jmaElements": [
        {
          "id": "trns",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/trns/{z}/{x}/{y}.png",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 8,
        "vectorLayer": null
      }
    },
    {
      "group": "disaster",
      "source": "flood",
      "kind": "vectorTile",
      "label": "洪水キキクル[河川]",
      "frameRule": {
        "kind": "current",
        "windowMinutes": null
      },
      "gridValue": null,
      "levelScale": "risk_levels",
      "description": "大雨で川があふれる危険度の高まりを、川に沿った色で示す気象庁の情報。",
      "jmaElements": [
        {
          "id": "flood",
          "targetTimesPaths": [
            "bosai/jmatile/data/risk/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/flood/{z}/{x}/{y}.pbf",
          "reader": "latest",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": "flood"
      }
    },
    {
      "group": "disaster",
      "source": "liden",
      "kind": "gridMark",
      "label": "落雷[発生地点]",
      "frameRule": {
        "kind": "latestObservation",
        "windowMinutes": 20
      },
      "gridValue": null,
      "levelScale": null,
      "description": "気象庁の雷の観測が捉えた、直近の雷の発生地点。",
      "jmaElements": [
        {
          "id": "liden",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/liden/data.geojson?id=liden",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 0
        }
      ],
      "tile": null
    }
  ],
  "compassLabels": [
    "北",
    "北東",
    "東",
    "南東",
    "南",
    "南西",
    "西",
    "北西"
  ],
  "alwaysShownAttributions": [
    "&copy; <a href=\"https://www.openstreetmap.org/copyright\" target=\"_blank\" rel=\"noreferrer\">OpenStreetMap contributors</a>",
    "<a href=\"https://maps.gsi.go.jp/development/ichiran.html\" target=\"_blank\" rel=\"noreferrer\">地理院タイル(標高タイル)</a>を加工して作成",
    "交通事故統計情報[警察庁]を加工して作成",
    "<a href=\"https://www.jma.go.jp/\" target=\"_blank\" rel=\"noreferrer\">気象庁ホームページ</a>(アメダス・警報・キキクル・ナウキャスト等)と気象庁「<a href=\"https://www.data.jma.go.jp/developer/gis.html\" target=\"_blank\" rel=\"noreferrer\">予報区等GISデータ</a>」を加工して作成",
    "気象庁メソ数値予報モデル(MSM)を加工して作成。配布: <a href=\"https://open-meteo.com/\" target=\"_blank\" rel=\"noreferrer\">Weather data by Open-Meteo.com</a> (<a href=\"https://creativecommons.org/licenses/by/4.0/\" target=\"_blank\" rel=\"noreferrer\">CC BY 4.0</a>)",
    "暑さ指数: 出典 <a href=\"https://www.wbgt.env.go.jp/\" target=\"_blank\" rel=\"noreferrer\">環境省熱中症予防情報サイト</a>",
    "土地被覆: <a href=\"https://livingatlas.arcgis.com/landcover/\" target=\"_blank\" rel=\"noreferrer\">Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)"
  ],
  "noDataDash": [
    1,
    2
  ],
  "road": {
    "lineWidthPx": 3,
    "trackOffsetStepPx": 2,
    "knownOpacity": 0.8,
    "unknownOpacity": 0.6,
    "underlayOpacity": 0.15,
    "inspectedWidthPx": 8
  },
  "point": {
    "radiusPx": 4,
    "fatalRadiusPx": 6,
    "nonFatalRadiusPx": 3,
    "strokeWidthPx": 1,
    "iconSizePx": 20,
    "opacityByLayer": {
      "stop_poi": 0.9,
      "accident_point": 0.75,
      "supply_poi": 0.9
    }
  },
  "area": {
    "opacity": 0.55,
    "hillshadeIlluminationDeg": 315,
    "hillshadeMethod": "igor",
    "hillshadeExaggeration": 1,
    "hillshadeShadowColor": "rgba(60, 50, 40, 0.55)",
    "hillshadeHighlightColor": "rgba(255, 252, 245, 0.55)",
    "terrainExaggeration": 5
  },
  "weather": {
    "markHaloWidthPx": 1.5,
    "windIconScaleRange": [
      0.9,
      2.6
    ],
    "windFullScaleMs": 15,
    "lightningIconScale": 0.8,
    "markSizeByZoom": [
      [
        10,
        0.75
      ],
      [
        13,
        1
      ],
      [
        16,
        1.5
      ],
      [
        19,
        2
      ]
    ],
    "floodLineWidthByZoom": [
      [
        6,
        1.5
      ],
      [
        10,
        3
      ],
      [
        14,
        5
      ]
    ],
    "rainbandOutlineWidthPx": 4,
    "rainbandOutlineCasingWidthPx": 6
  },
  "valueScale": {
    "difficultyBoundaries": [
      33,
      66
    ]
  },
  "route": {
    "lineWidthsPx": {
      "candidate": 2.5,
      "selectedHalo": 10,
      "splice": 3,
      "composite": 7,
      "slot": 4,
      "detail": 6
    },
    "casingWidthsPx": {
      "composite": 11,
      "slot": 8,
      "detail": 10
    },
    "opacities": {
      "selectedHalo": 0.25,
      "splice": 0.75,
      "candidate": 0.65,
      "slot": 0.85,
      "slotCasing": 0.85,
      "arrowHalo": 0.95
    },
    "spliceDash": [
      2,
      1.5
    ],
    "arrowSpacingPx": 80,
    "arrowHaloScale": 1.5,
    "arrowSizeByZoom": [
      [
        10,
        0.6
      ],
      [
        13,
        0.8
      ],
      [
        16,
        1.2
      ],
      [
        19,
        1.6
      ]
    ]
  }
} as const;
