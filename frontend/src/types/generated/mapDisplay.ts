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
    "roadTiles",
    "accidentTiles",
    "poiTiles",
    "gsiRelief",
    "gsiTerrain",
    "landcoverRaster",
    "ownFetch"
  ],
  "layerDataNatures": [
    "raw",
    "composite",
    "dynamic"
  ],
  "layerIds": [
    "highway",
    "surface",
    "tunnel",
    "oneway",
    "elevation",
    "stop_poi",
    "accident_point",
    "landcover",
    "supply_poi",
    "hillshade",
    "precipitationNowcast",
    "windVector",
    "disaster",
    "route"
  ],
  "layerKinds": [
    "static",
    "dynamic"
  ],
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
      "jmaElements": [
        {
          "id": "hrpns",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N1.json",
            "targetTimes_N2.json"
          ]
        },
        {
          "id": "rasrf",
          "pathGroup": "rasrf",
          "targetTimeFiles": [
            "targetTimes.json"
          ]
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
      "jmaElements": [],
      "attribution": "気象庁MSM",
      "tile": null
    },
    {
      "group": "precipitationNowcast",
      "source": "linearRainband",
      "kind": "rasterTile",
      "label": "線状降水帯予測",
      "jmaElements": [
        {
          "id": "sjfcstmap",
          "pathGroup": "rasrf",
          "targetTimeFiles": [
            "targetTimes.json"
          ]
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
      "jmaElements": [],
      "attribution": "気象庁MSM",
      "tile": null
    },
    {
      "group": "disaster",
      "source": "heavyRain",
      "kind": "rasterTile",
      "label": "大雨キキクル",
      "jmaElements": [
        {
          "id": "rain_mesh",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ]
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
      "jmaElements": [
        {
          "id": "land",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ]
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
      "jmaElements": [
        {
          "id": "inund",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ]
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
      "jmaElements": [
        {
          "id": "thns",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N3.json"
          ]
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
      "jmaElements": [
        {
          "id": "trns",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N3.json"
          ]
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
      "jmaElements": [
        {
          "id": "flood",
          "pathGroup": "risk",
          "targetTimeFiles": [
            "targetTimes.json"
          ]
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
      "jmaElements": [
        {
          "id": "liden",
          "pathGroup": "nowc",
          "targetTimeFiles": [
            "targetTimes_N3.json"
          ]
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
  "road": {
    "lineWidthPx": 3,
    "trackOffsetStepPx": 2,
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
      "spliceSelected": 5,
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
      "splice": 0.85
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
