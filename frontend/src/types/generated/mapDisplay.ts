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
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "surface",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "tunnel",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "oneway",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "elevation",
      "dataSource": "gsiRelief",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "stop_poi",
      "dataSource": "poi",
      "category": "trafficSafety",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "accident_point",
      "dataSource": "accident",
      "category": "trafficSafety",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "landcover",
      "dataSource": "landcoverRaster",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "supply_poi",
      "dataSource": "poi",
      "category": "amenity",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "hillshade",
      "dataSource": "gsiTerrain",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false
    },
    {
      "id": "precipitationNowcast",
      "dataSource": "ownFetch",
      "category": "weather",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false
    },
    {
      "id": "windVector",
      "dataSource": "ownFetch",
      "category": "weather",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false
    },
    {
      "id": "disaster",
      "dataSource": "ownFetch",
      "category": "disaster",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": true
    },
    {
      "id": "route",
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
      "jmaElements": [
        {
          "id": "hrpns",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N1.json",
            "targetTimes_N2.json"
          ],
          "reader": "nowcast",
          "refreshIntervalMs": 300000
        },
        {
          "id": "rasrf",
          "pathGroup": "rasrf",
          "targetTimeFiles": [
            "targetTimes.json"
          ],
          "reader": "latestFullRun",
          "refreshIntervalMs": 600000
        }
      ],
      "attribution": "気象庁",
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
      "jmaElements": [],
      "attribution": "気象庁MSM",
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
      "jmaElements": [
        {
          "id": "sjfcstmap",
          "pathGroup": "rasrf",
          "targetTimeFiles": [
            "targetTimes.json"
          ],
          "reader": "latest",
          "refreshIntervalMs": 600000
        }
      ],
      "attribution": "気象庁",
      "tile": {
        "minZoom": 4,
        "maxZoom": 10,
        "vectorLayer": null
      }
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
      "jmaElements": [],
      "attribution": "気象庁MSM",
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
      "jmaElements": [
        {
          "id": "rain_mesh",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ],
          "reader": "latest",
          "refreshIntervalMs": 600000
        }
      ],
      "attribution": "気象庁",
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
      "jmaElements": [
        {
          "id": "land",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ],
          "reader": "latest",
          "refreshIntervalMs": 600000
        }
      ],
      "attribution": "気象庁",
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
      "jmaElements": [
        {
          "id": "inund",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ],
          "reader": "latest",
          "refreshIntervalMs": 600000
        }
      ],
      "attribution": "気象庁",
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
      "jmaElements": [
        {
          "id": "thns",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N3.json"
          ],
          "reader": "nowcast",
          "refreshIntervalMs": 300000
        }
      ],
      "attribution": "気象庁",
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
      "jmaElements": [
        {
          "id": "trns",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N3.json"
          ],
          "reader": "nowcast",
          "refreshIntervalMs": 300000
        }
      ],
      "attribution": "気象庁",
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
      "label": "洪水キキクル（河川）",
      "frameRule": {
        "kind": "current",
        "windowMinutes": null
      },
      "gridValue": null,
      "jmaElements": [
        {
          "id": "flood",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ],
          "reader": "latest",
          "refreshIntervalMs": 600000
        }
      ],
      "attribution": "気象庁",
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
      "label": "落雷（発生地点）",
      "frameRule": {
        "kind": "latestObservation",
        "windowMinutes": 20
      },
      "gridValue": null,
      "jmaElements": [
        {
          "id": "liden",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N3.json"
          ],
          "reader": "nowcast",
          "refreshIntervalMs": 300000
        }
      ],
      "attribution": "気象庁",
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
    "交通事故統計情報（警察庁）を加工して作成",
    "土地被覆: <a href=\"https://livingatlas.arcgis.com/landcover/\" target=\"_blank\" rel=\"noreferrer\">Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)"
  ],
  "noDataDash": [
    1,
    2
  ],
  "road": {
    "lineWidthPx": 3,
    "trackOverlapPx": 1,
    "knownOpacity": 0.8,
    "unknownOpacity": 0.15,
    "inspectedWidthPx": 8
  },
  "point": {
    "radiusPx": 4,
    "fatalRadiusPx": 6,
    "nonFatalRadiusPx": 3,
    "strokeWidthPx": 1,
    "opacity": 0.9,
    "accidentOpacity": 0.75
  },
  "area": {
    "opacity": 0.55,
    "hillshadeIlluminationDeg": 315,
    "hillshadeMethod": "igor",
    "terrainExaggeration": 5
  },
  "weather": {
    "markHaloWidthPx": 1.5,
    "windIconScaleRange": [
      0.9,
      2.6
    ],
    "windFullScaleMs": 15,
    "lightningIconScale": 0.8
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
      "splice": 0.75
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
