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
            "description": "高速道路・国道・主要な県道など、車が遠くへ行くための太い通り[OSM の highway=motorway・trunk・primary とその連絡路]。",
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
            "description": "県道・市町村の主な道など、地域の中を結ぶ通り[OSM の highway=secondary・tertiary とその連絡路]。",
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
            "description": "住宅街の道・名前の付かない細い道・施設の中の通路など、主に近くへ行くための道[OSM の highway=residential・unclassified・living_street・service・road]。",
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
            "description": "自転車道・歩道・遊歩道・歩行者専用の道・階段など、車が通らない道[OSM の highway=cycleway・path・footway・pedestrian・bridleway・steps]。",
            "color": "#0e7e98"
          },
          {
            "key": "track",
            "label": "農道・林道",
            "values": [
              "track"
            ],
            "description": "田畑や山林へ入るための道。舗装も未舗装もある[OSM の highway=track]。",
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
            "description": "路面がアスファルト・舗装[種別不明]・チップシール舗装・コンクリート・コンクリート版・コンクリート帯[轍部のみ舗装]・石畳[切石]・レンガ舗装の道[OSM の surface タグ]。",
            "color": "#48886f"
          },
          {
            "key": "compacted",
            "label": "締め固め・細砂利",
            "values": [
              "compacted"
            ],
            "description": "路面が締固め砂利・細砂利の道[OSM の surface タグ]。",
            "color": "#3085a4"
          },
          {
            "key": "gravel",
            "label": "砂利・未舗装",
            "values": [
              "gravel"
            ],
            "description": "路面が砂利・小石敷き・岩盤・未舗装[種別不明]の道[OSM の surface タグ]。",
            "color": "#8873a1"
          },
          {
            "key": "soil",
            "label": "土・草・泥・砂",
            "values": [
              "soil"
            ],
            "description": "路面が土・地面[土・砂利混合]・土[地表面]・泥・砂・芝・草地・ウッドチップの道[OSM の surface タグ]。",
            "color": "#ab6a6c"
          },
          {
            "key": "cobblestone",
            "label": "石畳",
            "values": [
              "cobblestone"
            ],
            "description": "路面が石畳[玉石]・玉石舗装・玉石舗装[未加工]の道[OSM の surface タグ]。",
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
            "description": "固い路面の農道・林道。多くは舗装されている[OSM の tracktype=grade1]。",
            "color": "#433176"
          },
          {
            "key": "grade2",
            "label": "2 砂利[未舗装]",
            "values": [
              "grade2"
            ],
            "description": "おおむね固い未舗装の農道・林道。砂や土の混じった砂利道が多い[OSM の tracktype=grade2]。",
            "color": "#064f94"
          },
          {
            "key": "grade3",
            "label": "3 砂利と土が半々",
            "values": [
              "grade3"
            ],
            "description": "固い部分と柔らかい部分が半々の未舗装の農道・林道[OSM の tracktype=grade3]。",
            "color": "#036793"
          },
          {
            "key": "grade4",
            "label": "4 土・草が主",
            "values": [
              "grade4"
            ],
            "description": "土・砂・草が主で、固い部分が少し混じる未舗装の農道・林道[OSM の tracktype=grade4]。",
            "color": "#0e7e98"
          },
          {
            "key": "grade5",
            "label": "5 土・草・砂",
            "values": [
              "grade5"
            ],
            "description": "固い材料が無く、締まっていない土・砂・草の農道・林道[OSM の tracktype=grade5]。",
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
            "description": "トンネルの中を通る区間[OSM の tunnel タグ]。",
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
            "description": "一方向にしか進めない道。環状交差点も含み、自転車だけ両方向に通れる道は含まない[OSM の oneway・oneway:bicycle・junction タグ]。",
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
            "description": "信号機。信号付きの横断歩道もここに入る[OSM の highway=traffic_signals など]。",
            "color": "#885270"
          },
          {
            "key": "crossing",
            "label": "横断歩道",
            "values": [
              "crossing"
            ],
            "description": "信号の無い横断歩道[OSM の highway=crossing]。",
            "color": "#8d5449"
          },
          {
            "key": "stop",
            "label": "一時停止",
            "values": [
              "stop"
            ],
            "description": "一時停止の標識がある所[OSM の highway=stop]。",
            "color": "#736134"
          },
          {
            "key": "give_way",
            "label": "徐行",
            "values": [
              "give_way"
            ],
            "description": "相手に道を譲る（徐行する）標識がある所[OSM の highway=give_way]。",
            "color": "#496c44"
          },
          {
            "key": "level_crossing",
            "label": "踏切",
            "values": [
              "level_crossing",
              "railway_crossing"
            ],
            "description": "線路（路面電車を含む）を渡る所。車道の踏切も歩道・自転車道の踏切も入る[OSM の railway タグ]。",
            "color": "#016f6b"
          },
          {
            "key": "barrier",
            "label": "車止め・ゲート",
            "values": [
              "barrier"
            ],
            "description": "車止めの柱・ゲート・柵など、道をふさいで止まるか押して通る所[OSM の barrier タグ]。",
            "color": "#0c6b8b"
          },
          {
            "key": "traffic_calming",
            "label": "ハンプ・狭さく",
            "values": [
              "traffic_calming"
            ],
            "description": "車の速度を落とさせる段差（ハンプ）や道幅の絞り込み[OSM の traffic_calming タグ]。",
            "color": "#5e5f8d"
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
            "description": "当事者に自転車が含まれる事故[警察庁の交通事故統計の当事者種別]。",
            "color": "#5791ba"
          },
          {
            "key": "other",
            "label": "その他",
            "values": [
              false
            ],
            "description": "当事者に自転車が含まれない事故（車どうし・車と歩行者など）。",
            "color": "#a7865c"
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
            ],
            "description": "死者が1人以上記録された事故[警察庁の交通事故統計の死者数]。"
          },
          {
            "key": "non_fatal",
            "label": "死亡以外",
            "values": [
              false
            ],
            "description": "死者の記録が無い事故（負傷事故）。"
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
            "description": "コンビニエンスストア[OSM の shop=convenience]。",
            "glyph": "bag",
            "color": "#7d89ba"
          },
          {
            "key": "vending_drinks",
            "label": "飲料自販機",
            "values": [
              "vending_drinks"
            ],
            "description": "飲み物か食べ物を売ると書かれた自動販売機[OSM の amenity=vending_machine と vending タグ]。",
            "glyph": "bottle",
            "color": "#b47a99"
          },
          {
            "key": "vending_unknown",
            "label": "自販機(中身不明)",
            "values": [
              "vending_unknown"
            ],
            "description": "何を売るかが書かれていない自動販売機。飲み物が買えるとは限らない。",
            "glyph": "question",
            "color": "#b77e6a"
          },
          {
            "key": "toilets",
            "label": "トイレ",
            "values": [
              "toilets"
            ],
            "description": "公衆トイレなど、地図のデータにトイレとして載っている所[OSM の amenity=toilets]。",
            "glyph": "toilet",
            "color": "#908e5c"
          },
          {
            "key": "drinking_water",
            "label": "給水",
            "values": [
              "drinking_water"
            ],
            "description": "水飲み場など、飲み水をくめる所[OSM の amenity=drinking_water]。",
            "glyph": "drop",
            "color": "#57987e"
          },
          {
            "key": "bicycle_parking",
            "label": "駐輪場",
            "values": [
              "bicycle_parking"
            ],
            "description": "自転車を止められる所[OSM の amenity=bicycle_parking]。",
            "glyph": "parking",
            "color": "#3b97ad"
          }
        ],
        "missing_semantics": null
      }
    ]
  }
] as const;
