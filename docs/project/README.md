# PTR 椤圭洰姝ｅ紡鏂囨。

鏈洰褰曟槸 /home/zzq/PTR/therapy_robot 鐨勫敮涓€姝ｅ紡璇存槑鍏ュ彛銆備互鍚庢柊浠诲姟鍙洿鏂版湰鐩綍涓搴旀枃妗ｏ紝涓嶅啀鏂板缓 archive銆乸rogress銆乻ummary銆乭istory 鎴栧钩琛岃鏄庣洰褰曘€?
## 褰撳墠缁撹

- 褰撳墠涓诲垎鏀細main
- 褰撳墠鏈€鏂颁富鍒嗘敮鎻愪氦锛?92d9c697f314b20c4b8e86ed9883f79c1ea6ff3锛圚1 collector encoder read optional锛?- 褰撳墠宸ヤ綔鏍戝瓨鍦ㄧ敤鎴锋湭鎻愪氦淇敼锛歞ocs/H1-READONLY-COLLECTOR.md銆乼ests/test_h1_readonly_collector.py锛涙暣鐞嗚繃绋嬩繚鐣欙紝涓嶈鐩栥€佷笉鍥炴粴銆?- 鏈€鏂?B8 2/3/4 闆嗘垚鎻愪氦锛?65ef6d34ab7b084154eac8ed61682fec9d9ad21
- B8 闆嗘垚鍐呭锛?4a186a9627e1443258eb364748b8d0ad8a7a9d9 鍙婂叾鍚庣画闆嗘垚瀹¤鎻愪氦銆?- Shared Memory ABI锛歏3锛屽畾涔夊湪 include/therapy_robot/shared_memory.hpp 鐨?SharedState锛岄粯璁ょ‖浠舵ā寮忓叧闂€?- H1锛氬綋鍓嶄粎鍦ㄩ檺瀹氱殑瀹炰綋鍙鍙嶉瀹¤鑼冨洿鍐呬负 H1_ENTITY_READONLY_PASS锛?0 鏉″弽棣堟牱鏈€佹湭鍔ㄤ綔瀹¤锛夈€傝繖涓嶆槸瀹屾暣 H1 瀹夊叏楠屾敹 PASS锛涙€ュ仠銆佺湅闂ㄧ嫍銆佹姳闂搞€侀檺浣嶃€佺鎾炲拰 homed/zeroed 浠嶆湭褰㈡垚瀹屾暣瀹炰綋璇佹嵁銆?- Nano锛氬綋鍓嶉儴缃插揩鐓т笌 Nano 澶囦唤閫愰」 SHA-256 涓€鑷达紝浣?provenance 浠嶄负 BACKUP_SNAPSHOT_MATCHED_SOURCE_COMMIT_MAPPING_PENDING锛涘湪 source-to-deployment 鏄犲皠瀹屾垚鍓嶏紝涓嶅绉板綋鍓?main 宸查獙璇侀儴缃?PASS銆倆zqVM 浠呮槸杞欢寮€鍙戜富鏈恒€?- 瀹炰綋鏉冮檺锛歟xecution_allowed=false銆乪ntity_action_authorized=false銆乪ntity_motion_authorized=false锛涙湰鐩綍涓嶄骇鐢熸垨鍙戦€佺數鏈哄懡浠ゃ€?- 鏈鏁寸悊澶囦唤锛?home/zzq/PTR/therapy_robot/docs-reorganization-backup-20260824T140646Z/

## 鏂囨。瀵艰埅

1. 01-寮€鍙戣鐭?md
2. 02-椤圭洰鏋舵瀯涓庝唬鐮佷綅缃?md
3. 03-鍔熻兘涓庡疄楠屾祦绋?md
4. 04-闃舵杩涘害.md
5. 05-鐗堟湰涓庨儴缃茶褰?md
6. 06-娴嬭瘯涓庤瘉鎹储寮?md
7. 07-鍘嗗彶鏁村悎璁板綍.md

## 淇濈暀璧勬枡

- 鐢垫満鍗忚鍘熸枃锛歞ocs/鐢垫満鍗忚/
- 鍘熷纰版挒杈圭晫璇存槑锛歞ocs/鏈虹纰版挒杈圭晫.md
- 浠诲姟鍗★細docs/tasks/
- 娴嬭瘯銆佸疄楠屽拰瀹炰綋鍙鍘熷璇佹嵁锛歞ocs/progress/evidence/
- 鍘嗗彶褰掓。绱㈠紩锛歞ocs/archive/
- PTR 澶栭儴闂褰掓。銆丯ano 澶囦唤鍜岀▼搴忓浠戒笉鍦ㄦ湰鐩綍涓紝涓旀湰娆℃湭淇敼銆?

褰撳墠缁熶竴瑙勫垯锛欻1_ENTITY_READONLY_PASS 鍙〃绀哄疄浣撳弽棣堣鍙栧拰鏈姩浣滃璁￠€氳繃锛沞xecution_allowed=false銆乪ntity_action_authorized=false銆乪ntity_motion_authorized=false 缁х画淇濇寔锛屼换浣曞疄浣撹繍鍔ㄤ粛闇€鍗曠嫭鎺堟潈銆侼ano provenance 鐨?source-to-deployment 鏄犲皠浠嶅緟瀹屾垚銆俙n

