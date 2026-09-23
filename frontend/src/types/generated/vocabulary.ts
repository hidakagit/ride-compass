// 生成物。`backend/scripts/export_openapi.py`が書き出す。手で編集しない。
export const vocabulary = {
  "warningBadge": {
    "jma": [
      {
        "level": "advisory",
        "label": "注意報",
        "color": "#f59e0b"
      },
      {
        "level": "warning",
        "label": "警報",
        "color": "#dc2626"
      },
      {
        "level": "severe_warning",
        "label": "厳重警戒",
        "color": "#be123c"
      },
      {
        "level": "emergency_warning",
        "label": "特別警報",
        "color": "#9333ea"
      }
    ],
    "flood": [
      {
        "level": "advisory",
        "label": "氾濫注意報",
        "color": "#f59e0b"
      },
      {
        "level": "warning",
        "label": "氾濫警報",
        "color": "#dc2626"
      },
      {
        "level": "severe_warning",
        "label": "氾濫危険警報",
        "color": "#be123c"
      },
      {
        "level": "emergency_warning",
        "label": "氾濫特別警報",
        "color": "#9333ea"
      }
    ],
    "wbgt": [
      {
        "level": "advisory",
        "label": "注意",
        "color": "#4d7c0f"
      },
      {
        "level": "warning",
        "label": "警戒",
        "color": "#ca8a04"
      },
      {
        "level": "severe_warning",
        "label": "厳重警戒",
        "color": "#ea580c"
      },
      {
        "level": "emergency_warning",
        "label": "危険",
        "color": "#b91c1c"
      }
    ]
  },
  "weatherCategories": [
    {
      "key": "clear",
      "label": "晴れ",
      "codes": [
        0,
        1
      ]
    },
    {
      "key": "cloudy",
      "label": "くもり",
      "codes": [
        2,
        3
      ]
    },
    {
      "key": "fog",
      "label": "霧",
      "codes": [
        45,
        48
      ]
    },
    {
      "key": "rain",
      "label": "雨",
      "codes": [
        51,
        53,
        55,
        56,
        57,
        61,
        63,
        65,
        66,
        67,
        80,
        81,
        82
      ]
    },
    {
      "key": "snow",
      "label": "雪",
      "codes": [
        71,
        73,
        75,
        77,
        85,
        86
      ]
    },
    {
      "key": "thunderstorm",
      "label": "雷雨",
      "codes": [
        95,
        96,
        99
      ]
    }
  ],
  "weatherCategoryFallback": "cloudy",
  "materialPopulations": [
    {
      "key": "way",
      "label": "Way"
    },
    {
      "key": "edge",
      "label": "Edge"
    }
  ],
  "materialMissingSemantics": [
    {
      "key": "unknown",
      "title": "評価に影響する欠損",
      "hint": "元データが無い区間では、この材料を使う軸が評価対象外になる。"
    },
    {
      "key": "definite",
      "title": "タグ不在を確定値として評価する材料（参考）",
      "hint": "欠損は「該当なし」を意味し、評価に穴は開かない。"
    }
  ]
} as const;
