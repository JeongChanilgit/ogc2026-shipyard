# OGC2026 Rebuild DEVLOG

Append-only experiment log for the z3-aware LBBD rebuild (see `notes/rebuild-architecture-2026-06-14.html`).
Each entry: config (env) + per-instance z1/z2/z3/obj/wall + wins-vs-competitor. Recorded by `notes/devlog/score.py`.
Per-sequence (LBBD iteration) traces: `[REBUILD_SEQ]` on stderr, summarized by `notes/devlog/seqlog.py`.

Competitor target (`notes/competitor-2026-06-11.json`): total obj 1,143,358 ; win = strictly lower official obj per instance ; goal ≥13/20 (stretch 15/20).

Reusable primitive map: `notes/devlog/integration-map.md`.
Validation rule: adoption = full-20 paired ×2 ; mini-gate (fail-fast) = prob_14 + prob_20.
Archive of pre-rebuild src: `archive/src-snapshot-2026-06-14-pre-rebuild.zip`.

---

## 2026-06-14 03:42:46 — baseline_at600_2026-06-13

_Pre-rebuild reference: gate200_v2 default pipeline @600s per-instance (run_solver_once schema)._

**TAG=baseline_at600_2026-06-13  WINS=9/20  losses=11  ties=0  infeas=0  miss=0  tot_ours=1643317.0  tot_comp=1139442.3  delta=+503875**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           1499        9785       -8286      0     2    391  WIN WIN
prob_2           3690        6624       -2934      0    15    392  WIN WIN
prob_3          76630       50642      +25988      0   407    392  loss  <<<
prob_4          46011       16917      +29094      0   154    383  loss  <<<
prob_5          64402       70580       -6178      0   360    391  WIN WIN
prob_6          99920       72400      +27520      0   591    393  loss  <<<
prob_7          74997       86021      -11024      0   394    392  WIN WIN
prob_8          11252       12908       -1656      0     8    387  WIN WIN
prob_9          64675       80034      -15359      0   382    497  WIN WIN
prob_10         76041       98957      -22916      0   522    417  WIN WIN
prob_11         45703       31899      +13804      0   338    507  loss  <<<
prob_12        114786       94110      +20676      0   770    496  loss  <<<
prob_13        113500       76685      +36815      0   805    393  loss  <<<
prob_14         90963       67302      +23661      1   505    589  loss  <<<
prob_15         50783       48206       +2577      0   226    520  loss  <<<
prob_16         42900       50047       -7147      0   205    448  WIN WIN
prob_17         75492       62070      +13422      0   384    403  loss  <<<
prob_18         98240       40206      +58034      0   704    590  loss  <<<
prob_19         62980       72951       -9971      0   368    486  WIN WIN
prob_20        428853       91096     +337757     12   783    591  loss  <<<
```

## 2026-06-14 03:42:47 — baseline_gate200v2_paired

_Pre-rebuild reference: gate200_v2 default @200s, paired-min r1/r2._

**TAG=baseline_gate200v2_paired  WINS=9/20  losses=11  ties=0  infeas=0  miss=0  tot_ours=1515043.0  tot_comp=1139442.3  delta=+375601**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           1499        9785       -8286      0     2    126  WIN WIN
prob_2           3690        6624       -2934      0    15    129  WIN WIN
prob_3          76630       50642      +25988      0   407    128  loss  <<<
prob_4          46011       16917      +29094      0   154    129  loss  <<<
prob_5          64402       70580       -6178      0   360    120  WIN WIN
prob_6          79517       72400       +7117      0   461    120  loss  <<<
prob_7          74997       86021      -11024      0   394    125  WIN WIN
prob_8          11252       12908       -1656      0     8    112  WIN WIN
prob_9          64675       80034      -15359      0   382    164  WIN WIN
prob_10         85162       98957      -13795      0   578    168  WIN WIN
prob_11         45703       31899      +13804      0   338    171  loss  <<<
prob_12        104440       94110      +10330      0   702    170  loss  <<<
prob_13        104837       76685      +28152      0   689    170  loss  <<<
prob_14        104881       67302      +37579      0   777    190  loss  <<<
prob_15         50783       48206       +2577      0   226    172  loss  <<<
prob_16         42900       50047       -7147      0   205    131  WIN WIN
prob_17         78233       62070      +16163      0   405    170  loss  <<<
prob_18        103314       40206      +63108      0   726    174  loss  <<<
prob_19         62980       72951       -9971      0   368    166  WIN WIN
prob_20        309137       91096     +218041      7   898    189  loss  <<<
```

## 2026-06-14 04:03:42 — w1_t100

_Wave 1 foundation standalone @100s: ATC seed + z3-aware spill + SA. First from-scratch rebuild measurement._

`ENV: OGC_REBUILD=1,OGC_W1=1`

**TAG=w1_t100  WINS=1/20  losses=19  ties=0  infeas=0  miss=0  tot_ours=12380961.0  tot_comp=1139442.3  delta=+11241519**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1         129259        9785     +119474      4    58     85  loss  <<<
prob_2           3690        6624       -2934      0    15     85  WIN WIN
prob_3         111150       50642      +60508      0   515     85  loss  <<<
prob_4         102773       16917      +85856      2   232     85  loss  <<<
prob_5         129935       70580      +59354      1   498     85  loss  <<<
prob_6         196483       72400     +124083      2   815     85  loss  <<<
prob_7         154866       86021      +68845      0   865     85  loss  <<<
prob_8          30224       12908      +17316      0   134     85  loss  <<<
prob_9         117725       80034      +37691      0   728     85  loss  <<<
prob_10        135715       98957      +36758      1   684     86  loss  <<<
prob_11         80458       31899      +48559      0   546     85  loss  <<<
prob_12        185584       94110      +91474      0  1136     85  loss  <<<
prob_13        202849       76685     +126164      2  1153     85  loss  <<<
prob_14        277531       67302     +210229      5  1362     85  loss  <<<
prob_15         88043       48206      +39837      1   366     86  loss  <<<
prob_16         99425       50047      +49378      0   605     85  loss  <<<
prob_17         78233       62070      +16163      0   405     76  loss  <<<
prob_18        329474       40206     +289268     14   984     85  loss  <<<
prob_19        107912       72951      +34961      0   688     85  loss  <<<
prob_20       9819632       91096    +9728536    362  1066     86  loss  <<<
```

## 2026-06-14 04:26:18 — w4_t100

_Full W1-W4 stack @100s: LBBD cap-cut + ban-cut, timing only at finalize._

`ENV: OGC_REBUILD=1,OGC_W1..W4=1`

**TAG=w4_t100  WINS=4/20  losses=16  ties=0  infeas=0  miss=0  tot_ours=5159707.0  tot_comp=1139442.3  delta=+4020265**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1          30590        9785      +20805      1     2     44  loss  <<<
prob_2           3690        6624       -2934      0    15     49  WIN WIN
prob_3          95010       50642      +44368      0   599     85  loss  <<<
prob_4         102773       16917      +85856      2   232     56  loss  <<<
prob_5         103699       70580      +33118      0   656     85  loss  <<<
prob_6         152976       72400      +80576      0   998     85  loss  <<<
prob_7          87660       86021       +1639      0   485     85  loss  <<<
prob_8          11252       12908       -1656      0     8     85  WIN WIN
prob_9          95715       80034      +15681      0   606     85  loss  <<<
prob_10         96215       98957       -2742      0   705     85  WIN WIN
prob_11         77896       31899      +45997      0   578     85  loss  <<<
prob_12        147728       94110      +53618      0  1101     85  loss  <<<
prob_13        211228       76685     +134543      2  1231     84  loss  <<<
prob_14        600128       67302     +532826     27   844     85  loss  <<<
prob_15         68204       48206      +19998      0   353     85  loss  <<<
prob_16         66208       50047      +16161      0   406     85  loss  <<<
prob_17         78233       62070      +16163      0   405     91  loss  <<<
prob_18        177812       40206     +137606      0  1288     85  loss  <<<
prob_19         65499       72951       -7452      0   363     85  WIN WIN
prob_20       2887191       91096    +2796095    104   747     86  loss  <<<
```

## 2026-06-14 04:47:46 — w4b_t100

_Corrected config @100s._

`ENV: OGC_REBUILD W1-W4 + timing-in-loop + multicut + prob17fix`

**TAG=w4b_t100  WINS=6/20  losses=14  ties=0  infeas=0  miss=0  tot_ours=4159557.0  tot_comp=1139442.3  delta=+3020115**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1          30590        9785      +20805      1     2     28  loss  <<<
prob_2           3690        6624       -2934      0    15     49  WIN WIN
prob_3          89570       50642      +38928      0   534     85  loss  <<<
prob_4          43658       16917      +26741      0   152     85  loss  <<<
prob_5          77749       70580       +7168      0   469     85  loss  <<<
prob_6         146007       72400      +73607      1   738     85  loss  <<<
prob_7          96551       86021      +10530      0   581     85  loss  <<<
prob_8          11252       12908       -1656      0     8     85  WIN WIN
prob_9          66140       80034      -13894      0   400     85  WIN WIN
prob_10         95662       98957       -3295      0   704     85  WIN WIN
prob_11         72870       31899      +40971      0   546     85  loss  <<<
prob_12        193151       94110      +99041      0  1200     85  loss  <<<
prob_13        211228       76685     +134543      2  1231     84  loss  <<<
prob_14        600128       67302     +532826     27   844     85  loss  <<<
prob_15         63214       48206      +15008      0   318     85  loss  <<<
prob_16         49953       50047         -94      0   246     85  WIN WIN
prob_17        100290       62070      +38220      0   590     85  loss  <<<
prob_18        228929       40206     +188723      0  1693     85  loss  <<<
prob_19         65499       72951       -7452      0   363     85  WIN WIN
prob_20       1913426       91096    +1822330     68   682     87  loss  <<<
```

## 2026-06-14 05:04:46 — additive_estimate

_Portfolio estimate: per-instance min(rebuild@100, legacy@200) vs competitor. Tests if rebuild ADDS wins._

**TAG=additive_estimate  WINS=9/20  losses=11  ties=0  infeas=0  miss=0  tot_ours=1512690.0  tot_comp=1139442.3  delta=+373248**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           1499        9785       -8286      0     2    126  WIN WIN
prob_2           3690        6624       -2934      0    15     49  WIN WIN
prob_3          76630       50642      +25988      0   407    128  loss  <<<
prob_4          43658       16917      +26741      0   152     85  loss  <<<
prob_5          64402       70580       -6178      0   360    120  WIN WIN
prob_6          79517       72400       +7117      0   461    120  loss  <<<
prob_7          74997       86021      -11024      0   394    125  WIN WIN
prob_8          11252       12908       -1656      0     8     85  WIN WIN
prob_9          64675       80034      -15359      0   382    164  WIN WIN
prob_10         85162       98957      -13795      0   578    168  WIN WIN
prob_11         45703       31899      +13804      0   338    171  loss  <<<
prob_12        104440       94110      +10330      0   702    170  loss  <<<
prob_13        104837       76685      +28152      0   689    170  loss  <<<
prob_14        104881       67302      +37579      0   777    190  loss  <<<
prob_15         50783       48206       +2577      0   226    172  loss  <<<
prob_16         42900       50047       -7147      0   205    131  WIN WIN
prob_17         78233       62070      +16163      0   405    170  loss  <<<
prob_18        103314       40206      +63108      0   726    174  loss  <<<
prob_19         62980       72951       -9971      0   368    166  WIN WIN
prob_20        309137       91096     +218041      7   898    189  loss  <<<
```

## 2026-06-14 06:05:11 — pkfull200

_Full-20 with repositioning packer wired into decode._

`ENV: OGC_REBUILD W1/W3/W4 + PACKER @200s`

**TAG=pkfull200  WINS=6/20  losses=14  ties=0  infeas=0  miss=0  tot_ours=3233986.0  tot_comp=1139442.3  delta=+2094544**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1          30590        9785      +20805      1     2     28  loss  <<<
prob_2           3690        6624       -2934      0    15     48  WIN WIN
prob_3          89570       50642      +38928      0   534    170  loss  <<<
prob_4          41780       16917      +24863      0   134    170  loss  <<<
prob_5         102858       70580      +32278      0   602    170  loss  <<<
prob_6         180200       72400     +107800      2   670     88  loss  <<<
prob_7          96551       86021      +10530      0   581    170  loss  <<<
prob_8          11252       12908       -1656      0     8    170  WIN WIN
prob_9          74250       80034       -5784      0   452    170  WIN WIN
prob_10         95662       98957       -3295      0   704    170  WIN WIN
prob_11         72870       31899      +40971      0   546    170  loss  <<<
prob_12        116893       94110      +22783      0   810    170  loss  <<<
prob_13        225447       76685     +148762      3  1124    162  loss  <<<
prob_14        158760       67302      +91458      2   823    140  loss  <<<
prob_15         63214       48206      +15008      0   318    170  loss  <<<
prob_16         49953       50047         -94      0   246    170  WIN WIN
prob_17        100290       62070      +38220      0   590    170  loss  <<<
prob_18        113206       40206      +73000      0   778    170  loss  <<<
prob_19         65499       72951       -7452      0   363    170  WIN WIN
prob_20       1541451       91096    +1450355     52  1089    163  loss  <<<
```

## 2026-06-14 11:27:21 — unified200

_BIG CHANGE: unified CP-SAT-guided crane-aware greedy constructive._

`ENV: OGC_REBUILD_UNIFIED @200s`

**TAG=unified200  WINS=5/20  losses=15  ties=0  infeas=0  miss=0  tot_ours=1955483.0  tot_comp=1139442.3  delta=+816041**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1          29065        9785      +19280      0   142     12  loss  <<<
prob_2           3690        6624       -2934      0    15      2  WIN WIN
prob_3          94640       50642      +43998      0   514      2  loss  <<<
prob_4         172800       16917     +155883      3   494     25  loss  <<<
prob_5          79406       70580       +8826      0   445      2  loss  <<<
prob_6         137604       72400      +65204      0   844     19  loss  <<<
prob_7          82785       86021       -3236      0   463      2  WIN WIN
prob_8          11252       12908       -1656      0     8      2  WIN WIN
prob_9         118260       80034      +38226      0   764      8  loss  <<<
prob_10         94605       98957       -4352      0   650      2  WIN WIN
prob_11        101017       31899      +69118      0   704     12  loss  <<<
prob_12        140735       94110      +46625      0   987      5  loss  <<<
prob_13        142907       76685      +66222      0   974     19  loss  <<<
prob_14        135052       67302      +67750      0   984     17  loss  <<<
prob_15         46751       48206       -1455      0   192      4  WIN WIN
prob_16         80300       50047      +30253      0   475      2  loss  <<<
prob_17        110283       62070      +48213      0   667      3  loss  <<<
prob_18        118042       40206      +77836      0   802      6  loss  <<<
prob_19         75123       72951       +2172      0   463      3  loss  <<<
prob_20        181166       91096      +90070      0  1336     26  loss  <<<
```

## 2026-06-14 11:28:47 — additive_unified

_min(unified, legacy) per instance vs competitor._

**TAG=additive_unified  WINS=10/20  losses=10  ties=0  infeas=0  miss=0  tot_ours=1383040.0  tot_comp=1139442.3  delta=+243598**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           1499        9785       -8286      0     2    126  WIN WIN
prob_2           3690        6624       -2934      0    15      2  WIN WIN
prob_3          76630       50642      +25988      0   407    128  loss  <<<
prob_4          46011       16917      +29094      0   154    129  loss  <<<
prob_5          64402       70580       -6178      0   360    120  WIN WIN
prob_6          79517       72400       +7117      0   461    120  loss  <<<
prob_7          74997       86021      -11024      0   394    125  WIN WIN
prob_8          11252       12908       -1656      0     8      2  WIN WIN
prob_9          64675       80034      -15359      0   382    164  WIN WIN
prob_10         85162       98957      -13795      0   578    168  WIN WIN
prob_11         45703       31899      +13804      0   338    171  loss  <<<
prob_12        104440       94110      +10330      0   702    170  loss  <<<
prob_13        104837       76685      +28152      0   689    170  loss  <<<
prob_14        104881       67302      +37579      0   777    190  loss  <<<
prob_15         46751       48206       -1455      0   192      4  WIN WIN
prob_16         42900       50047       -7147      0   205    131  WIN WIN
prob_17         78233       62070      +16163      0   405    170  loss  <<<
prob_18        103314       40206      +63108      0   726    174  loss  <<<
prob_19         62980       72951       -9971      0   368    166  WIN WIN
prob_20        181166       91096      +90070      0  1336     26  loss  <<<
```

## 2026-06-14 11:41:45 — augment200

_Real submission path: legacy gate + unified candidate._

`ENV: OGC_REBUILD_AUGMENT=1 (legacy+unified candidate)`

**TAG=augment200  WINS=10/20  losses=10  ties=0  infeas=0  miss=0  tot_ours=1421952.0  tot_comp=1139442.3  delta=+282510**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           1499        9785       -8286      0     2    126  WIN WIN
prob_2           3690        6624       -2934      0    15    129  WIN WIN
prob_3          76630       50642      +25988      0   407    128  loss  <<<
prob_4          46011       16917      +29094      0   154    166  loss  <<<
prob_5          64402       70580       -6178      0   360    119  WIN WIN
prob_6          93111       72400      +20711      0   538    129  loss  <<<
prob_7          74997       86021      -11024      0   394    119  WIN WIN
prob_8          11252       12908       -1656      0     8    114  WIN WIN
prob_9          64675       80034      -15359      0   382    168  WIN WIN
prob_10         78113       98957      -20844      0   525    139  WIN WIN
prob_11         45703       31899      +13804      0   338    168  loss  <<<
prob_12        120316       94110      +26206      0   830    170  loss  <<<
prob_13        113599       76685      +36914      0   808    168  loss  <<<
prob_14        112610       67302      +45308      2   538    189  loss  <<<
prob_15         46751       48206       -1455      0   192    191  WIN WIN
prob_16         42900       50047       -7147      0   205    131  WIN WIN
prob_17         78233       62070      +16163      0   405    168  loss  <<<
prob_18        103314       40206      +63108      0   726    174  loss  <<<
prob_19         62980       72951       -9971      0   368    166  WIN WIN
prob_20        181166       91096      +90070      0  1336    190  loss  <<<
```

## 2026-06-14 11:54:00 — augment_paired

_Augment paired x2 adoption gate._

**TAG=augment_paired  WINS=10/20  losses=10  ties=0  infeas=0  miss=0  tot_ours=1414917.0  tot_comp=1139442.3  delta=+275475**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           1499        9785       -8286      0     2    126  WIN WIN
prob_2           3690        6624       -2934      0    15    129  WIN WIN
prob_3          76630       50642      +25988      0   407    128  loss  <<<
prob_4          46011       16917      +29094      0   154    166  loss  <<<
prob_5          64402       70580       -6178      0   360    119  WIN WIN
prob_6          93111       72400      +20711      0   538    129  loss  <<<
prob_7          74997       86021      -11024      0   394    119  WIN WIN
prob_8          11252       12908       -1656      0     8    114  WIN WIN
prob_9          64675       80034      -15359      0   382    168  WIN WIN
prob_10         78113       98957      -20844      0   525    139  WIN WIN
prob_11         45703       31899      +13804      0   338    168  loss  <<<
prob_12        119049       94110      +24939      0   826    168  loss  <<<
prob_13        108583       76685      +31898      0   746    190  loss  <<<
prob_14        111858       67302      +44556      2   539    189  loss  <<<
prob_15         46751       48206       -1455      0   192    191  WIN WIN
prob_16         42900       50047       -7147      0   205    131  WIN WIN
prob_17         78233       62070      +16163      0   405    168  loss  <<<
prob_18        103314       40206      +63108      0   726    174  loss  <<<
prob_19         62980       72951       -9971      0   368    166  WIN WIN
prob_20        181166       91096      +90070      0  1336    190  loss  <<<
```

## 2026-06-14 13:44:43 — ucpp300

_Exact CP-SAT packer in unified, full-20 @300._

`ENV: unified+cppack @300 standalone`

**TAG=ucpp300  WINS=6/20  losses=14  ties=0  infeas=0  miss=0  tot_ours=1763595.0  tot_comp=1139442.3  delta=+624153**

```
inst         ours_obj    comp_obj         gap     z1    z3   wall  res
prob_1           3695        9785       -6090      0    12    116  WIN WIN
prob_2           3690        6624       -2934      0    15      3  WIN WIN
prob_3          63290       50642      +12648      0   200    121  loss  <<<
prob_4          48149       16917      +31232      0   216    247  loss  <<<
prob_5          69456       70580       -1124      0   367     84  WIN WIN
prob_6          99712       72400      +27312      0   601     99  loss  <<<
prob_7          82785       86021       -3236      0   463     94  WIN WIN
prob_8          18320       12908       +5412      0    48      7  loss  <<<
prob_9         118260       80034      +38226      0   764    255  loss  <<<
prob_10         88053       98957      -10904      0   603     30  WIN WIN
prob_11         52640       31899      +20741      0   355    104  loss  <<<
prob_12        140735       94110      +46625      0   987    133  loss  <<<
prob_13        161512       76685      +84827      1   974    255  loss  <<<
prob_14        188386       67302     +121084      3   984    255  loss  <<<
prob_15         43805       48206       -4401      0   160     52  WIN WIN
prob_16         80300       50047      +30253      0   475     36  loss  <<<
prob_17         73142       62070      +11072      1   297     74  loss  <<<
prob_18        118042       40206      +77836      0   802    255  loss  <<<
prob_19         75123       72951       +2172      0   463     83  loss  <<<
prob_20        234500       91096     +143404      2  1336    255  loss  <<<
```
