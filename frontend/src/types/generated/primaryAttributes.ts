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
            "color": "#3b4554"
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
            "color": "#56657b"
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
            "color": "#75869f"
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
            "color": "#9ca8ba"
          },
          {
            "key": "track",
            "label": "農道・林道",
            "values": [
              "track"
            ],
            "color": "#c3cad5"
          }
        ]
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
        "property": "surface",
        "categories": [
          {
            "key": "asphalt",
            "label": "アスファルト",
            "values": [
              "asphalt",
              "paved",
              "chipseal"
            ],
            "color": "#456187"
          },
          {
            "key": "concrete",
            "label": "コンクリート",
            "values": [
              "concrete",
              "concrete:plates",
              "concrete:lanes"
            ],
            "color": "#4b4587"
          },
          {
            "key": "stones",
            "label": "石畳・敷石",
            "values": [
              "paving_stones",
              "sett",
              "cobblestone",
              "unhewn_cobblestone",
              "bricks"
            ],
            "color": "#6b4587"
          },
          {
            "key": "gravel",
            "label": "砂利・締固め",
            "values": [
              "gravel",
              "fine_gravel",
              "compacted",
              "pebblestone",
              "rock"
            ],
            "color": "#874581"
          },
          {
            "key": "dirt",
            "label": "土・草・砂",
            "values": [
              "unpaved",
              "dirt",
              "ground",
              "earth",
              "mud",
              "sand",
              "grass",
              "woodchips"
            ],
            "color": "#874561"
          }
        ]
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
            "color": "#874b45"
          }
        ]
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
            "color": "#876b45"
          }
        ]
      }
    ]
  },
  {
    "attr_id": "elevation",
    "label": "標高",
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
            "color": "#818745"
          },
          {
            "key": "crossing",
            "label": "横断歩道",
            "values": [
              "crossing"
            ],
            "color": "#618745"
          },
          {
            "key": "stop",
            "label": "一時停止",
            "values": [
              "stop"
            ],
            "color": "#45874b"
          },
          {
            "key": "give_way",
            "label": "徐行",
            "values": [
              "give_way"
            ],
            "color": "#45876b"
          },
          {
            "key": "level_crossing",
            "label": "踏切",
            "values": [
              "level_crossing",
              "railway_crossing"
            ],
            "color": "#458187"
          },
          {
            "key": "barrier",
            "label": "車止め・ゲート",
            "values": [
              "barrier"
            ],
            "color": "#6886b1"
          },
          {
            "key": "traffic_calming",
            "label": "ハンプ・狭さく",
            "values": [
              "traffic_calming"
            ],
            "color": "#6e68b1"
          }
        ]
      }
    ]
  },
  {
    "attr_id": "accident_point",
    "label": "事故地点",
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
            "color": "#86b168"
          },
          {
            "key": "other",
            "label": "その他",
            "values": [
              false
            ],
            "color": "#68b16e"
          }
        ]
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
            ],
            "color": "#68b192"
          },
          {
            "key": "non_fatal",
            "label": "死亡以外",
            "values": [
              false
            ],
            "color": "#68abb1"
          }
        ]
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
    "label": "土地被覆",
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
            "color": "#9268b1"
          },
          {
            "key": "vending_drinks",
            "label": "飲料自販機",
            "values": [
              "vending_drinks"
            ],
            "color": "#b168ab"
          },
          {
            "key": "vending_unknown",
            "label": "自販機(中身不明)",
            "values": [
              "vending_unknown"
            ],
            "color": "#b16886"
          },
          {
            "key": "toilets",
            "label": "トイレ",
            "values": [
              "toilets"
            ],
            "color": "#b16e68"
          },
          {
            "key": "drinking_water",
            "label": "給水",
            "values": [
              "drinking_water"
            ],
            "color": "#b19268"
          },
          {
            "key": "bicycle_parking",
            "label": "駐輪場",
            "values": [
              "bicycle_parking"
            ],
            "color": "#abb168"
          }
        ]
      }
    ]
  }
] as const;
