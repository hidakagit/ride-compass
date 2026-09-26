// 生成物。`backend/scripts/export_openapi.py`が書き出す。手で編集しない。
export const primaryAttributes = [
  {
    "attr_id": "highway",
    "label": "道路の種類",
    "geometry": "line",
    "tile_kind": "road_surface",
    "display_axes": [
      {
        "key": "highway",
        "label": "",
        "property": "highway",
        "categories": [
          {
            "key": "arterial",
            "label": "幹線道路",
            "values": [
              "motorway",
              "motorway_link",
              "trunk",
              "trunk_link",
              "primary",
              "primary_link"
            ],
            "color": "#433176"
          },
          {
            "key": "secondary",
            "label": "主要道",
            "values": [
              "secondary",
              "secondary_link",
              "tertiary",
              "tertiary_link"
            ],
            "color": "#064f94"
          },
          {
            "key": "local",
            "label": "生活道路",
            "values": [
              "residential",
              "unclassified",
              "living_street",
              "service",
              "road"
            ],
            "color": "#036793"
          },
          {
            "key": "cycleway",
            "label": "自転車・歩行者道",
            "values": [
              "cycleway",
              "path",
              "footway",
              "pedestrian",
              "bridleway",
              "steps"
            ],
            "color": "#0e7e98"
          },
          {
            "key": "track",
            "label": "農道・林道",
            "values": [
              "track"
            ],
            "color": "#0d959d"
          }
        ],
        "missing_semantics": "unknown"
      }
    ]
  },
  {
    "attr_id": "lanes",
    "label": "車線数",
    "geometry": "line",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "maxspeed",
    "label": "制限速度",
    "geometry": "line",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "cycleway",
    "label": "自転車インフラ",
    "geometry": "line",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "surface",
    "label": "路面の種類",
    "geometry": "line",
    "tile_kind": "road_surface",
    "display_axes": [
      {
        "key": "surface",
        "label": "",
        "property": "surface_class",
        "categories": [
          {
            "key": "paved",
            "label": "舗装",
            "values": [
              "paved"
            ],
            "color": "#48886f"
          },
          {
            "key": "compacted",
            "label": "締め固め・細砂利",
            "values": [
              "compacted"
            ],
            "color": "#3085a4"
          },
          {
            "key": "gravel",
            "label": "砂利・未舗装",
            "values": [
              "gravel"
            ],
            "color": "#8873a1"
          },
          {
            "key": "soil",
            "label": "土・草・泥・砂",
            "values": [
              "soil"
            ],
            "color": "#ab6a6c"
          },
          {
            "key": "cobblestone",
            "label": "石畳",
            "values": [
              "cobblestone"
            ],
            "color": "#8a7b4c"
          }
        ],
        "missing_semantics": "unknown"
      }
    ]
  },
  {
    "attr_id": "tracktype",
    "label": "農道・林道の等級",
    "geometry": "line",
    "tile_kind": "road_surface",
    "display_axes": [
      {
        "key": "tracktype",
        "label": "",
        "property": "tracktype",
        "categories": [
          {
            "key": "grade1",
            "label": "1 舗装・固く締まる",
            "values": [
              "grade1"
            ],
            "color": "#433176"
          },
          {
            "key": "grade2",
            "label": "2 砂利[未舗装]",
            "values": [
              "grade2"
            ],
            "color": "#064f94"
          },
          {
            "key": "grade3",
            "label": "3 砂利と土が半々",
            "values": [
              "grade3"
            ],
            "color": "#036793"
          },
          {
            "key": "grade4",
            "label": "4 土・草が主",
            "values": [
              "grade4"
            ],
            "color": "#0e7e98"
          },
          {
            "key": "grade5",
            "label": "5 土・草・砂",
            "values": [
              "grade5"
            ],
            "color": "#0d959d"
          }
        ],
        "missing_semantics": "unknown"
      }
    ]
  },
  {
    "attr_id": "motor_vehicle_access",
    "label": "自動車通行可否",
    "geometry": "line",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "lit",
    "label": "街灯",
    "geometry": "line",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "tunnel",
    "label": "トンネル",
    "geometry": "line",
    "tile_kind": "road_surface",
    "display_axes": [
      {
        "key": "tunnel",
        "label": "",
        "property": "tunnel",
        "categories": [
          {
            "key": "tunnel",
            "label": "トンネル",
            "values": [
              true
            ],
            "color": "#8e729e"
          }
        ],
        "missing_semantics": "definite"
      }
    ]
  },
  {
    "attr_id": "oneway",
    "label": "一方通行",
    "geometry": "line",
    "tile_kind": "road_surface",
    "display_axes": [
      {
        "key": "oneway",
        "label": "",
        "property": "oneway",
        "categories": [
          {
            "key": "oneway",
            "label": "一方通行",
            "values": [
              true
            ],
            "color": "#a66e5b"
          }
        ],
        "missing_semantics": "definite"
      }
    ]
  },
  {
    "attr_id": "elevation",
    "label": "標高図",
    "geometry": "area",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "stop_poi",
    "label": "停止要因",
    "geometry": "point",
    "tile_kind": "poi",
    "display_axes": [
      {
        "key": "kind",
        "label": "",
        "property": "kind",
        "categories": [
          {
            "key": "traffic_signals",
            "label": "信号",
            "values": [
              "traffic_signals"
            ],
            "color": "#a36b89"
          },
          {
            "key": "crossing",
            "label": "横断歩道",
            "values": [
              "crossing"
            ],
            "color": "#a96d61"
          },
          {
            "key": "stop",
            "label": "一時停止",
            "values": [
              "stop"
            ],
            "color": "#8e7a4c"
          },
          {
            "key": "give_way",
            "label": "徐行",
            "values": [
              "give_way"
            ],
            "color": "#61855c"
          },
          {
            "key": "level_crossing",
            "label": "踏切",
            "values": [
              "level_crossing",
              "railway_crossing"
            ],
            "color": "#2e8984"
          },
          {
            "key": "barrier",
            "label": "車止め・ゲート",
            "values": [
              "barrier"
            ],
            "color": "#3684a6"
          },
          {
            "key": "traffic_calming",
            "label": "ハンプ・狭さく",
            "values": [
              "traffic_calming"
            ],
            "color": "#7878a8"
          }
        ],
        "missing_semantics": null
      }
    ]
  },
  {
    "attr_id": "accident_point",
    "label": "事故[警察庁統計]",
    "geometry": "point",
    "tile_kind": "accident",
    "display_axes": [
      {
        "key": "party",
        "label": "当事者",
        "property": "involves_bicycle",
        "categories": [
          {
            "key": "bicycle",
            "label": "自転車関連",
            "values": [
              true
            ],
            "color": "#4682aa"
          },
          {
            "key": "other",
            "label": "その他",
            "values": [
              false
            ],
            "color": "#97764e"
          }
        ],
        "missing_semantics": null
      },
      {
        "key": "severity",
        "label": "重大度",
        "property": "fatal",
        "categories": [
          {
            "key": "fatal",
            "label": "死亡事故",
            "values": [
              true
            ]
          },
          {
            "key": "non_fatal",
            "label": "死亡以外",
            "values": [
              false
            ]
          }
        ],
        "missing_semantics": null
      }
    ]
  },
  {
    "attr_id": "intersection",
    "label": "交差点",
    "geometry": "point",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "landcover",
    "label": "緑と水",
    "geometry": "area",
    "tile_kind": null,
    "display_axes": []
  },
  {
    "attr_id": "supply_poi",
    "label": "補給・休憩ポイント",
    "geometry": "point",
    "tile_kind": "poi",
    "display_axes": [
      {
        "key": "kind",
        "label": "",
        "property": "kind",
        "categories": [
          {
            "key": "convenience",
            "label": "コンビニ",
            "values": [
              "convenience"
            ],
            "color": "#6d7aaa"
          },
          {
            "key": "vending_drinks",
            "label": "飲料自販機",
            "values": [
              "vending_drinks"
            ],
            "color": "#a36b89"
          },
          {
            "key": "vending_unknown",
            "label": "自販機(中身不明)",
            "values": [
              "vending_unknown"
            ],
            "color": "#a66e5b"
          },
          {
            "key": "toilets",
            "label": "トイレ",
            "values": [
              "toilets"
            ],
            "color": "#807e4d"
          },
          {
            "key": "drinking_water",
            "label": "給水",
            "values": [
              "drinking_water"
            ],
            "color": "#48886f"
          },
          {
            "key": "bicycle_parking",
            "label": "駐輪場",
            "values": [
              "bicycle_parking"
            ],
            "color": "#25879d"
          }
        ],
        "missing_semantics": null
      }
    ]
  }
] as const;
