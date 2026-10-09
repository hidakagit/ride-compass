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
      "description": "元にする地図のデータに値が無く、どの行にも分けられない道。道が無いのではなく、値が分からない。"
    },
    "undetermined": {
      "label": "向きで決まらない",
      "description": "選んだ走行方位とほぼ直角に交わり、その向きでは値が決まらない道（勾配なら、登りか下りかが決まらない）。データが無いのではなく、走行方位を変えると色が付く。"
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
      "key": "stop_place",
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
      "id": "elevation",
      "label": "標高図",
      "dataSource": "gsiRelief",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "国土地理院の色別標高図を重ねる"
      ],
      "panelHint": [
        "国土地理院の色別標高図を重ねる"
      ],
      "hideMissingRows": false
    },
    {
      "id": "hillshade",
      "label": "起伏",
      "dataSource": "gsiTerrain",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "斜面に陰影を付ける[平地は塗らない]"
      ],
      "panelHint": [
        "国土地理院の標高データから斜面の陰影を作る。平らな所は塗らないため、下の地図の色が残る"
      ],
      "hideMissingRows": false
    },
    {
      "id": "landcover",
      "label": "緑と水",
      "dataSource": "landcoverRaster",
      "category": "terrain",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "周囲の緑・水辺・農地を面で重ねる[建物は塗らない]"
      ],
      "panelHint": [
        "衛星画像から分類した10m四方ごとの土地の使われ方です。1区画に1種類だけが入るため、評価軸が使う「道路の周囲100mの割合」とは違い、混ざらずそのまま見えます。建物は塗りません——広い範囲を単色で覆い、基礎地図を隠すだけになるためです。地図の道を押して開く内訳には建物も出ます。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "highway",
      "label": "道路の種類",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "道路の種類を色で表示[「幹線道路」ほど濃い紫、「農道・林道」ほど明るい水色]"
      ],
      "panelHint": [
        "OSMのhighwayタグを区分にまとめて色分けしています。「幹線道路」が最も濃く、下位の道ほど明るい色です。ほかの道路のレイヤーと一緒に表示すると、同じ道に線を横へ並べて描きます。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "surface",
      "label": "路面の種類",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "路面の材質を色で表示[舗装・砂利・土など]"
      ],
      "panelHint": [
        "OSMのsurfaceタグ[路面の材質]を区分にまとめて色分けしています。区分に当てはまらない値の道は「その他」で出します。タグの無い道[データなし]は郊外ではほとんどの道に当たり、値のある道を埋もれさせるため、最初は隠してあり、凡例のチェックで出せます[データなしは未舗装という意味ではありません]。"
      ],
      "hideMissingRows": true
    },
    {
      "id": "tracktype",
      "label": "農道・林道の等級",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "農道・林道の路面の等級を色で表示[「1 舗装・固く締まる」ほど濃い紫、「5 土・草・砂」ほど明るい水色]"
      ],
      "panelHint": [
        "OSMのtracktypeタグ[農道・林道の路面の固さの等級]を色分けしています。路面の材質[surfaceタグ]とは別のタグで、材質のタグが無い農道・林道にも付いていることがあります。タグの無い道は「データなし」です。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "tunnel",
      "label": "トンネル",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "トンネル区間[OSMのtunnelタグ]を色分け表示"
      ],
      "panelHint": [
        "OSMのtunnelタグが該当する区間です。",
        {
          "name": "axes",
          "before": "評価軸",
          "after": "の材料の1つです。"
        }
      ],
      "hideMissingRows": false
    },
    {
      "id": "oneway",
      "label": "一方通行",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "来た道を戻れない区間を色分け表示"
      ],
      "panelHint": [
        "その向きにしか通れない区間です。上下線が分かれているだけの道[逆方向が数m隣にある]は除いてあります。ルート探索は既に一方通行の向きを守っており[逆走経路自体が生成されません]、このレイヤーは表示のみで評価には影響しません。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "cycleway",
      "label": "自転車レーン",
      "dataSource": "road_surface",
      "category": "roadCondition",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "自転車の走る場所を色で表示[自転車道・自転車レーン・共用の道]"
      ],
      "panelHint": [
        "OSMの自転車のためのタグ[cycleway・highway=cycleway・bicycle]から、自転車の走る場所を区分にまとめて色分けしています。1本の道が複数に当たれば、車道から分けられた方で出します。当てはまらない道は最初は隠してあり、凡例のチェックで出せます。",
        {
          "name": "axes",
          "before": "評価軸",
          "after": "の材料の1つです。"
        }
      ],
      "hideMissingRows": true
    },
    {
      "id": "stop_poi",
      "label": "停止要因",
      "dataSource": "poi",
      "category": "trafficSafety",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "信号、横断歩道、一時停止、徐行、踏切、車止め・ゲート、ハンプ・狭さくの位置を種別ごとに色分け表示"
      ],
      "panelHint": [
        "信号、横断歩道、一時停止、徐行、踏切、車止め・ゲート、ハンプ・狭さくの位置です。",
        {
          "name": "axes",
          "before": "評価軸",
          "after": "が近傍のこれらを数えて算出しているものを、種別ごとの色分けで直接確認できます。"
        }
      ],
      "hideMissingRows": false
    },
    {
      "id": "supply_poi",
      "label": "補給・休憩ポイント",
      "dataSource": "poi",
      "category": "amenity",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "コンビニ、飲料自販機、自販機(中身不明)、トイレ、給水、駐輪場の位置を種別ごとに色分け表示"
      ],
      "panelHint": [
        "コンビニ、飲料自販機、自販機(中身不明)、トイレ、給水、駐輪場の位置です。自販機は飲み物が買えると分かっているものだけを「飲料自販機」として出し、売っているものが分からないものは「自販機(中身不明)」として区別します[たばこ・切符の機械は出しません]。コンビニはOverture Mapsの地点のうちチェーンの店を、ほかはOSMのデータを出します。どれも閉店・撤去にデータが追いついていないことがあります。現地の状況と異なる場合があることをご留意ください。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "stop_place",
      "label": "立ち寄り先",
      "dataSource": "stop_place",
      "category": "amenity",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "飲食店、銭湯・温泉、自転車、景色・名所、宿、寺社の位置を群ごとに色分け表示"
      ],
      "panelHint": [
        "飲食店、銭湯・温泉、自転車、景色・名所、宿、寺社の位置です。寺社は国の文化財の建造物を持つものを、ほかはOverture Mapsの地点を出します。閉店にデータが追いついていないことがあります。現地の状況と異なる場合があることをご留意ください。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "accident_point",
      "label": "事故[警察庁統計]",
      "dataSource": "accident",
      "category": "trafficSafety",
      "kind": "static",
      "dataNature": "raw",
      "defaultOn": false,
      "description": [
        "警察庁交通事故統計オープンデータ",
        {
          "name": "accidentYears",
          "before": "[",
          "after": "]"
        },
        "の発生地点を表示"
      ],
      "panelHint": [
        "警察庁が公開する交通事故統計オープンデータ[本票",
        {
          "name": "accidentYears",
          "before": "、",
          "after": ""
        },
        "]の発生地点です。死亡事故は円を大きく表示します。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "precipitationNowcast",
      "label": "降水ナウキャスト",
      "dataSource": "ownFetch",
      "category": "weather",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false,
      "description": [
        "気象庁の降水ナウキャスト・降水短時間予報・線状降水帯予測マップ・線状降水帯の雨域と、数値予報モデルが計算した降水量を重ねて表示[実況〜60分先は5分刻み、60分〜15時間先は気象庁の降水短時間予報、以降は気象庁の数値予報モデルMSMの計算値を1時間刻みで、予報ではなく誤差を含みうる。線状降水帯予測マップは現在〜3時間先、線状降水帯の雨域は実況〜30分先の間だけ追加で重畳]"
      ],
      "panelHint": [
        "気象庁の高解像度降水ナウキャストです。ONにすると地図上に時刻スライダーが現れ、実況[直近]から60分先までの雨雲の分布を切り替えて確認できます。60分より先は、同じ気象庁の降水短時間予報へ自動的に切り替わり、15時間先まで確認できます——こちらは実況の外挿ではなく数値予報モデルによる予測のため、先になるほど不確実性が増します。15時間より先は、風と同じ仕組み[気象庁の数値予報モデルMSMが格子点ごとに計算した降水量]で、格子を降水強度に応じた色で塗る表示へさらに切り替わり、1〜3日先まで確認できます[降水短時間予報よりも粗い5kmメッシュのモデルの計算値で、予報ではなく誤差を含みえます]。加えて、現在〜3時間先の間だけ、気象庁の線状降水帯予測マップを重ねて表示します[今後3時間以内に大雨のおそれがある領域を赤で示すもので、予測は格子単位のため矩形に見えます。今まさに発生している線状降水帯の雨域を示すものではありません]。今まさに発生している線状降水帯は、実況から30分先までの間、その雨域を赤い輪郭線で重ねます[気象庁が線状降水帯を解析しているときだけ出ます]。非公式の内部APIを利用している実況・60分先までの部分・線状降水帯予測マップ・線状降水帯の雨域は、取得に失敗することがあります。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "windVector",
      "label": "風[矢印]",
      "dataSource": "ownFetch",
      "category": "weather",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": false,
      "description": [
        "気象庁の数値予報モデルMSMが計算した風向・風速を矢印で表示[1〜3日先まで。予報ではなく誤差を含みうる]"
      ],
      "panelHint": [
        "気象庁MSM[メソ数値予報モデル、5kmメッシュ]が計算した風向・風速を格子点で矢印表示します。モデルの計算値で、予報ではなく、誤差を含みえます。矢印の向きが風向、長さ・太さ・色の濃淡が風速の強さを表します。ごく弱い風の地点は矢印を表示しません。ONにすると地図上に時刻スライダーが現れ、1時間刻みで切り替えられます[先まで見られる範囲は配信中の計算値の長さによって1〜3日の間で変わります]。",
        {
          "name": "axes",
          "before": "走行方位に対する向かい風/追い風の強さは、道路の色分けで評価軸",
          "after": "を選ぶと別途確認できます。"
        }
      ],
      "hideMissingRows": false
    },
    {
      "id": "disaster",
      "label": "災害",
      "dataSource": "ownFetch",
      "category": "disaster",
      "kind": "static",
      "dataNature": "dynamic",
      "defaultOn": true,
      "description": [
        "気象庁の雷ナウキャスト・竜巻発生確度・落雷[発生地点]・大雨キキクル・土砂災害キキクル・浸水キキクル・洪水キキクル[河川]をまとめて表示[雷ナウキャスト・竜巻発生確度は時刻に連動、落雷[発生地点]は直近の観測、大雨キキクル・土砂災害キキクル・浸水キキクル・洪水キキクル[河川]は現在の危険度のみ]"
      ],
      "panelHint": [
        "気象庁の防災情報をまとめて表示します。雷ナウキャスト・竜巻発生確度は時刻スライダーに連動し、実況[直近]から60分先までを切り替えて確認できます。落雷[発生地点]は観測だけのため、最新の観測より先の時刻には出ません。大雨キキクル・土砂災害キキクル・浸水キキクル・洪水キキクル[河川]は色分けした現在の危険度で、「現在の危険度」単一値のみの配信のため時刻スライダーには連動しません。平常時は危険度ゼロの領域が透明のため、ONのままでも地図の見た目は変わりません。非公式の内部APIを利用しているため、取得に失敗することがあります。"
      ],
      "hideMissingRows": false
    },
    {
      "id": "route",
      "label": "ルート",
      "dataSource": "ownFetch",
      "category": null,
      "kind": "dynamic",
      "dataNature": "raw",
      "defaultOn": true,
      "description": [
        "選択中ルート沿いの情報",
        {
          "name": "routeLenses",
          "before": "[",
          "after": "]"
        },
        "を色分け表示"
      ],
      "panelHint": null,
      "hideMissingRows": false
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
          "dataDelayMinutes": 0,
          "forecastMinutes": 60
        },
        {
          "id": "rasrf",
          "targetTimesPaths": [
            "bosai/jmatile/data/rasrf/targetTimes.json"
          ],
          "urlTemplate": "bosai/jmatile/data/rasrf/{basetime}/{member}/{validtime}/surf/rasrf/{z}/{x}/{y}.png",
          "reader": "latestFullRun",
          "refreshIntervalMs": 600000,
          "dataDelayMinutes": 0,
          "forecastMinutes": 900
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
          "dataDelayMinutes": 0,
          "forecastMinutes": null
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
          "dataDelayMinutes": 10,
          "forecastMinutes": null
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
          "dataDelayMinutes": 10,
          "forecastMinutes": 30
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
          "dataDelayMinutes": 0,
          "forecastMinutes": null
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
          "dataDelayMinutes": 0,
          "forecastMinutes": null
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
          "dataDelayMinutes": 0,
          "forecastMinutes": null
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
      "description": "雷の激しさと雷が起こる可能性を、活動度の段階で示す気象庁の実況と60分先までの予測。",
      "jmaElements": [
        {
          "id": "thns",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/thns/{z}/{x}/{y}.png",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 0,
          "forecastMinutes": 60
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
      "description": "竜巻などの激しい突風が起こりやすい所を、確度の段階で示す気象庁の実況と60分先までの予測。",
      "jmaElements": [
        {
          "id": "trns",
          "targetTimesPaths": [
            "bosai/jmatile/data/nowc/targetTimes_N3.json"
          ],
          "urlTemplate": "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/trns/{z}/{x}/{y}.png",
          "reader": "nowcast",
          "refreshIntervalMs": 300000,
          "dataDelayMinutes": 0,
          "forecastMinutes": 60
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
          "dataDelayMinutes": 0,
          "forecastMinutes": null
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
          "dataDelayMinutes": 0,
          "forecastMinutes": null
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
    "土地被覆: <a href=\"https://livingatlas.arcgis.com/landcover/\" target=\"_blank\" rel=\"noreferrer\">Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)",
    "「位置参照情報（大字町丁目・街区レベル）令和6年」（国土交通省）、「Geolonia 住所データ」（株式会社Geolonia） <a href=\"https://geolonia.github.io/japanese-addresses/\" target=\"_blank\" rel=\"noreferrer\">https://geolonia.github.io/japanese-addresses/</a>、「アドレス・ベース・レジストリ」（デジタル庁） <a href=\"https://www.digital.go.jp/policies/base_registry_address_tos/\" target=\"_blank\" rel=\"noreferrer\">https://www.digital.go.jp/policies/base_registry_address_tos/</a> をもとに、株式会社情報試作室が加工した jageocoder 用住所データベース（街区レベル）を利用",
    "立ち寄り先: <a href=\"https://overturemaps.org/\" target=\"_blank\" rel=\"noreferrer\">Overture Maps Foundation</a>の地点を、種類を選び近くの同じ店をまとめて加工。Data from Meta, Microsoft, PinMeTo, DAC (<a href=\"https://cdla.dev/permissive-2-0/\" target=\"_blank\" rel=\"noreferrer\">CDLA Permissive 2.0</a>), AllThePlaces (<a href=\"https://creativecommons.org/publicdomain/zero/1.0/\" target=\"_blank\" rel=\"noreferrer\">CC0 1.0</a>), Foursquare (Copyright 2024 Foursquare Labs, Inc. All rights reserved. Available under <a href=\"/licenses/apache-2.0.txt\" target=\"_blank\" rel=\"noreferrer\">Apache 2.0</a>. Foursquare data was transformed to the Overture schema. <a href=\"/licenses/foursquare-places-NOTICE.txt\" target=\"_blank\" rel=\"noreferrer\">NOTICE</a>)",
    "寺社: ジャパンサーチ「<a href=\"https://jpsearch.go.jp/database/bunka\" target=\"_blank\" rel=\"noreferrer\">文化遺産オンライン（文化庁・国立情報学研究所）</a>」のメタデータを改変して利用（所有者で寺社ごとにまとめた）"
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
    "strokeWidthPx": 1,
    "iconSizePx": 20,
    "opacityByLayer": {
      "stop_poi": 0.9,
      "accident_point": 0.75,
      "supply_poi": 0.9,
      "stop_place": 0.9
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
    ],
    "difficultyDecimals": 1
  },
  "route": {
    "lineWidthsPx": {
      "candidate": 2.5,
      "selectedHalo": 10,
      "splice": 3,
      "composite": 7,
      "detail": 6
    },
    "casingWidthsPx": {
      "composite": 11,
      "detail": 10
    },
    "opacities": {
      "selectedHalo": 0.25,
      "splice": 0.75,
      "candidate": 0.65,
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
