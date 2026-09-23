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
            "color": "#272d31"
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
            "color": "#38434d"
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
            "color": "#4a5c6a"
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
            "color": "#5c7589"
          },
          {
            "key": "track",
            "label": "農道・林道",
            "values": [
              "track"
            ],
            "color": "#6f8fa9"
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
            "color": "#48886f"
          },
          {
            "key": "concrete",
            "label": "コンクリート",
            "values": [
              "concrete",
              "concrete:plates",
              "concrete:lanes"
            ],
            "color": "#3085a4"
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
            "color": "#8873a1"
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
            "color": "#ab6a6c"
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
            "color": "#8a7b4c"
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
            "color": "#8e729e"
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
            "color": "#a66e5b"
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
            ]
          },
          {
            "key": "non_fatal",
            "label": "死亡以外",
            "values": [
              false
            ]
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
        ]
      }
    ]
  }
] as const;
