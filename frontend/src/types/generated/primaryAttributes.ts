// 生成物。`backend/scripts/export_openapi.py`が書き出す。手で編集しない。
export const primaryAttributes = [
  {
    "attr_id": "highway",
    "label": "道路の種類",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "lanes",
    "label": "車線数",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "maxspeed",
    "label": "制限速度",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "cycleway",
    "label": "自転車インフラ",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": "road_surface",
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": [
      {
        "key": "cycleway",
        "label": "",
        "property": "cycleway_class",
        "categories": [
          {
            "key": "separated",
            "label": "自転車道",
            "values": [
              "separated"
            ],
            "description": "車道から分けられた、自転車の通る道[OSM の highway=cycleway・cycleway=track]。",
            "color": "#a66e5b"
          },
          {
            "key": "lane",
            "label": "自転車レーン",
            "values": [
              "lane"
            ],
            "description": "車道の上に線で区切った、自転車の通る帯[OSM の cycleway=lane]。",
            "color": "#48886f"
          },
          {
            "key": "shared",
            "label": "共用の道",
            "values": [
              "shared"
            ],
            "description": "バス・車と共用の帯か、自転車も通ってよい歩道・遊歩道[OSM の cycleway=share_busway・shared_lane、highway=footway・path かつ bicycle=yes・designated]。",
            "color": "#6d7aaa"
          }
        ],
        "missing_semantics": "definite"
      }
    ]
  },
  {
    "attr_id": "surface",
    "label": "路面の種類",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": "road_surface",
    "point_thinning": null,
    "point_name_property": null,
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
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "motor_vehicle_access",
    "label": "自動車通行可否",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "lit",
    "label": "街灯",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "tunnel",
    "label": "トンネル",
    "geometry": "line",
    "point_facts": [],
    "tile_kind": "road_surface",
    "point_thinning": null,
    "point_name_property": null,
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
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "elevation",
    "label": "標高図",
    "geometry": "area",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "stop_poi",
    "label": "停止要因",
    "geometry": "point",
    "point_facts": [],
    "tile_kind": "poi",
    "point_thinning": null,
    "point_name_property": null,
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
            "description": "信号機。信号付きの横断歩道もここに入る[OSM の highway=traffic_signals・crossing]。",
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
    "point_facts": [
      {
        "property": "occurred_year",
        "label": "発生年"
      }
    ],
    "tile_kind": "accident",
    "point_thinning": null,
    "point_name_property": null,
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
            "description": "死者が1人以上記録された事故[事故後24時間以内の死者。警察庁の交通事故統計の死者数]。",
            "radius_px": 6
          },
          {
            "key": "non_fatal",
            "label": "死亡以外",
            "values": [
              false
            ],
            "description": "死者の記録が無い事故（負傷事故）。",
            "radius_px": 3
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
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "landcover",
    "label": "緑と水",
    "geometry": "area",
    "point_facts": [],
    "tile_kind": null,
    "point_thinning": null,
    "point_name_property": null,
    "display_axes": []
  },
  {
    "attr_id": "supply_poi",
    "label": "補給・休憩ポイント",
    "geometry": "point",
    "point_facts": [],
    "tile_kind": "poi",
    "point_thinning": null,
    "point_name_property": "name",
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
            "description": "コンビニのチェーンの店[Overture Maps の地点のコンビニの分類のうち、チェーンの名前に当たるもの]。",
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
  },
  {
    "attr_id": "stop_place",
    "label": "立ち寄り先",
    "geometry": "point",
    "point_facts": [],
    "tile_kind": "stop_place",
    "point_thinning": {
      "rows": [
        "temple_shrine",
        "bath",
        "bicycle",
        "lodging",
        "scenic",
        "eat_drink"
      ],
      "ratio_property": "confidence"
    },
    "point_name_property": "name",
    "display_axes": [
      {
        "key": "group",
        "label": "",
        "property": "group",
        "categories": [
          {
            "key": "eat_drink",
            "label": "飲食店",
            "values": [
              "eat_drink"
            ],
            "description": "飲食店・カフェ・酒場[Overture Maps の地点の飲食の分類]。",
            "glyph": "cup",
            "color": "#9f7439"
          },
          {
            "key": "bath",
            "label": "銭湯・温泉",
            "values": [
              "bath"
            ],
            "description": "銭湯・温泉・サウナ[Overture Maps の地点の分類]。",
            "glyph": "steam",
            "color": "#59884a"
          },
          {
            "key": "bicycle",
            "label": "自転車",
            "values": [
              "bicycle"
            ],
            "description": "自転車の店・修理・貸し自転車[Overture Maps の地点の分類]。",
            "glyph": "wrench",
            "color": "#018b89"
          },
          {
            "key": "scenic",
            "label": "景色・名所",
            "values": [
              "scenic"
            ],
            "description": "公園・庭園・湖・滝・山・浜・城・展望台・博物館の類[Overture Maps の地点の分類]。",
            "glyph": "mountain",
            "color": "#0984ba"
          },
          {
            "key": "lodging",
            "label": "宿",
            "values": [
              "lodging"
            ],
            "description": "ホテル・旅館・民宿・キャンプ場の類[Overture Maps の地点の分類]。",
            "glyph": "bed",
            "color": "#956cad"
          },
          {
            "key": "temple_shrine",
            "label": "寺社",
            "values": [
              "temple_shrine"
            ],
            "description": "国の指定・登録の文化財の建造物を持つ寺社[文化遺産オンライン]。",
            "glyph": "gate",
            "color": "#bd606c"
          }
        ],
        "missing_semantics": null
      }
    ]
  }
] as const;
