# 과거 상태 기록 §38–50 — Custom AI v1.7.0~v1.10.6

`docs/latest_status.md`에서 분리한 원문이다. 절 번호는 원본 그대로 보존한다
(40번이 두 번 쓰인 원본의 실수도 그대로 둔다). 토라스크 교체, 캠페인 로스터,
프로토스 진영, 렌더/사운드/단축키 수정, 테스트 런처, 부속 건물 가설 반증까지의
기록이다.

## 38. Custom AI v1.7.0 토라스크 전역 교체

캠페인 유닛 이식의 첫 파일럿으로 모든 표준 울트라리스크를 토라스크로 전역
교체했다. 전체 `Swarm Story` 종속성을 넣는 방식은 로컬 API 맵에서 캠페인
카탈로그를 실제로 노출하지 않아 폐기했다. 대신 공개 추출 SC2 데이터에서 필요한
레코드와 자산 경로를 조사하고, `tools/campaign_data/torrasque/`의 작은 XML
조각만 런타임 맵에 병합하는 외과적 복사 방식을 사용한다.

스톡 AI 호환성을 위해 별도 토라스크 유닛 ID를 만들지 않고 `Ultralisk` ID 109를
그대로 유지했다. 별도 유닛 방식은 카탈로그상 사용 가능했지만 생산 ability ID가
0으로 남아 스톡 AI가 생산할 수 없었다. ID 109 부분 오버라이드 방식에서는 기존
애벌레 생산 ability ID 1348과 울트라 전략 지식을 그대로 사용한다. 토라스크는
500 체력, 방어력 3, 캠페인 토라스크 모델을 쓰며 치명 피해를 받으면 고치로 바뀌어
10초 뒤 부활한다. 부활 후 60초 동안은 다시 부활하지 않는다.

실제 SC2 5.0.16 엔진 검증 결과는 다음과 같다.

```text
CAMPAIGN_DEPENDENCY_NORMAL_START=PASS
runtime P1 Terran: 사령부 1 + SCV 8
runtime P2 Protoss: 연결체 1 + 탐사정 8
runtime P3 Zerg: 부화장 1 + 일벌레 8
runtime P4 Terran: 사령부 1 + SCV 8

TORRASQUE_REVIVE=PASS
TORRASQUE_SUPPLY_STABILITY=PASS
치명 피해 -> 고치(사용 인구 6 유지) -> 10초 후 체력 500으로 부활

unit_id=torrasque_replacement:109 available=True ability_id=1348
t=600s: 군락 1, 감염 구덩이 1
t=1000s: 울트라리스크 동굴 1, 토라스크 5
TORRASQUE_AI_PRODUCTION=PASS
```

실제 런처의 맵 생성은 캠페인 유닛 기능을 기본 활성화한다. GUI의 저그 빌드명도
`토라스크·저글링·맹독충`으로 변경했다. GUI·맵·런타임 파일 버전은
`Custom AI v1.7.0`이며 실행 맵은
`runtime/maps/europe-melee-custom-ai-v1.7.0.SC2Map`이다. 다음 순서는 변종 ADD,
랩터 업그레이드, 골리앗·프레데터·의무병 ADD, 프로토스 전역 부족 프리셋이다.

## 39. Custom AI v1.8.0 캠페인 로스터와 프로토스 전역 진영

확정했던 나머지 캠페인 유닛을 모두 추가했다. 저그는 변종과 랩터 진화,
테란은 골리앗·프레데터·의무병이다. 생산 버튼·요구 조건·모델·배우와
`ResponseData`의 생산 ability ID까지 유효했지만, Blizzard 멜리 AI는 신규 유닛
ID에 대한 `AISetStock` 요청을 1,500 게임 초 동안 한 기도 생산하지 않았다.

처음 시도한 Galaxy의 동적 `AbilityCommand` 생산 명령은 맵 초기화 트리거를
중단시켜 모든 정상 시작 유닛이 사라지는 회귀를 일으켰다. 이 방식은 폐기했다.
최종 방식은 기술 건물·현재 자원·가용 보급을 검사하고 실제 비용을 차감한 뒤,
생산 건물 옆에 한 기를 만들고 해당 생산 건물에 실제 빌드 시간만큼 쿨다운을
기록하는 전략 구매다. 일반 유닛·일꾼·보급·건설·업그레이드는 계속 정예 내장
AI가 담당한다. 랩터도 산란못과 번식지/군락, 광물 100·가스 100 조건에서 비용을
차감한 뒤 전역 업그레이드를 적용해 기존 및 이후 저글링을 강화한다.

실제 SC2 5.0.16 비실시간 장기 생산 시험 결과:

```text
t=300s raptor=True
t=400s aberration=0 medic=6
t=500s aberration=8 predator=1 medic=7
t=600s aberration=13 predator=10 medic=7
t=700s aberration=13 goliath=0 predator=10 medic=7
CAMPAIGN_AI_PRODUCTION=PASS
```

변종 생산은 실제 유충 한 기를 소모한다. 골리앗과 프레데터는 동일 군수공장의
캠페인 생산 쿨다운을 공유해 한 군수공장에서 병렬 생성되지 않는다. 골리앗은
100초 간격 출력 사이에 생성·교전·파괴되어 최종 행은 0이지만 누적 출현 조건을
충족했다. 카탈로그와 강제 생성 검사도 별도로 통과했다.

```text
SC2TeamAberration: id=2010 ability=1369 food=3 life=275
SC2TeamGoliath: id=2011 ability=609 food=2 life=150
SC2TeamPredator: id=2012 ability=610 food=3 life=140
SC2TeamMedic: id=2013 ability=579 food=2 life=60
SC2TeamRaptorEvolution: id=306
CAMPAIGN_ROSTER_CATALOG=PASS
CAMPAIGN_ROSTER_CREATE=PASS
```

전투 기능도 별도 프로브에서 확인했다.

최종 카탈로그는 부모 멀리 유닛의 무기를 그대로 상속하지 않는다. 변종은 캠페인식
기본 20 + 중장갑 20, 골리앗은 지상 18과 공중 합산 16 + 중장갑 16,
프레데터는 직접 15 + 근거리 응징장 광역 20의 전용 무기/피해 레코드를 쓴다.

```text
CAMPAIGN_COMBAT_SC2TEAMABERRATION=PASS damage=125
CAMPAIGN_COMBAT_SC2TEAMGOLIATH=PASS damage=125
CAMPAIGN_COMBAT_SC2TEAMPREDATOR=PASS damage=125
CAMPAIGN_COMBAT_GOLIATH_AIR=PASS damage=135
CAMPAIGN_COMBAT_MEDIC=PASS life=10->45
CAMPAIGN_COMBAT=PASS
```

GUI에는 모든 프로토스가 공유하는 전역 진영 선택을 추가했다. 기본 프로토스,
아이어, 네라짐, 정화자, 탈다림 중 하나를 선택한다. 스톡 AI 호환성을 위해 현재
범위는 표준 유닛 ID·생산·무기·능력을 보존하면서 대표 지상 유닛 배우 모델을
진영형으로 바꾸는 호환 외형 프리셋이다. 캠페인 캐스터 능력은 아직 넣지 않았다.
네 진영 모두 실제 엔진에서 연결체 1기와 탐사정 8기의 정상 시작을 확인했다.

```text
PROTOSS_FACTION_AIUR=PASS
PROTOSS_FACTION_NERAZIM=PASS
PROTOSS_FACTION_PURIFIER=PASS
PROTOSS_FACTION_TALDARIM=PASS
PROTOSS_FACTIONS=PASS
VERIFY_ALL[offline]=PASS (11 checks)
VERIFY_ALL[short-engine]=PASS (2 checks)
```

상세 수정 절차는 `docs/modify/campaign-units.md`에 정리했다. GUI·맵·런타임
버전은 `Custom AI v1.8.0`이며 최종 실행 맵은
`runtime/maps/europe-melee-custom-ai-v1.8.0.SC2Map`이다.

현재 저장 설정의 활성 12명 구성으로 최종 릴리스 맵 자체도 열었다. 논리 P4의
사람 저그가 런타임 P1로 배치되고 부화장 1기·일벌레 8기로 정상 시작했다.

```text
RELEASE_ENGINE_SMOKE=PASS players=12 human=P4->runtimeP1
race=Zerg townhall=1 workers=8
GUI_SMOKE=PASS faction=Standard slots=14
```

## 40. 캠페인 의무병 추종 및 릴리스 검증 고정 (2026-07-16)

의무병은 공격 능력이 없으므로 기존 지상군 공격 명령을 그대로 받으면 전투 병력을
따라가지 못할 수 있었다. Galaxy 지상군 명령 함수를 분리해 `SC2TeamMedic`에는 같은
목표점으로 이동 명령을, 나머지 전투 유닛에는 공격 명령을 보내도록 변경했다.
가속 엔진 프로브에 의무병을 직접 추가해 불곰과 함께 실제 이동하는지 고정했다.

```text
marauder distance_sq=697.5
medic distance_sq=688.3
STRATEGY_RUNTIME_TEST=PASS
STRATEGY_MEDIC_FOLLOW_TEST=PASS
VERIFY_ALL[short-engine]=PASS (2 checks)
```

연속 엔진 프로브 사이에는 SC2 프로세스가 사라진 직후에도 싱글턴 자원이 잠시
남는 경우가 있었다. 하네스가 프로세스 종료를 폴링한 뒤 짧은 안정화 시간을 두도록
해 두 프로브를 연속 실행할 때의 간헐적 API 포트 기동 실패를 제거했다.

이전 최종 v1.8.0 맵의 MapInfo와 Galaxy를 읽어 저장 설정이 프로브 픽스처로
덮인 사실을 확인하고, 실제 맵에 기록된 12명 구성(사람 논리 P4 저그, P7/P14
비활성, 서쪽 테란 대 동쪽 프로토스)을 복원했다. 같은 설정으로 최종 맵을 다시
생성했으며 SHA-256은 다음과 같다.

```text
A8700616935DB7E6940FB36BC87BB64DE0DABF8EBE8A9F4410C9DB4AF5367FEC
```

릴리스 맵 검증을 `verification/verify_release_map.py`와 `verification/verify_all.py --tier release-engine`로
보존했다. 저장 설정의 모든 비무작위 활성 플레이어에 대해 종족별 시작 본진 1기와
일꾼 8기를 확인한다.

```text
VERIFY_ALL[offline]=PASS (11 checks)
VERIFY_ALL[short-engine]=PASS (2 checks)
VERIFY_ALL[release-engine]=PASS (1 check)
RELEASE_ENGINE_SMOKE=PASS players=12 human=P4->runtimeP1
```

제한 없는 실행 환경에서 캠페인 장기 생산과 프로토스 네 진영을 다시 실행했다.
직전 두 번의 API 포트 실패는 제한된 샌드박스가 설치된 SC2 클라이언트를 띄우지
못한 결과였고 게임 로직 실패가 아니었다. 정상 환경의 최종 결과는 다음과 같다.

```text
t=300s raptor=True
t=400s aberration=3
t=500s aberration=12 medic=3
t=700s predator=7
t=800s aberration=13 predator=10 medic=9
CAMPAIGN_AI_PRODUCTION=PASS
PROTOSS_FACTION_AIUR=PASS nexus=1 probes=8
PROTOSS_FACTION_NERAZIM=PASS nexus=1 probes=8
PROTOSS_FACTION_PURIFIER=PASS nexus=1 probes=8
PROTOSS_FACTION_TALDARIM=PASS nexus=1 probes=8
PROTOSS_FACTIONS=PASS
```

진영 프로브가 `runtime/custom_ai_active.json`을 마지막 탈다림 픽스처로 바꾸므로,
마지막에는 저장된 12명/Standard 설정으로 v1.8.0 맵을 다시 생성하고 릴리스
엔진 티어를 재실행했다. 최종 해시는 위와 동일하며 SC2 프로세스는 정리한다.

토라스크 전체 경로도 최종 재검증했다. 정상 시작과 치명 피해 고치/10초 부활,
사용 인구 6 유지는 다시 PASS했다. 그러나 첫 장기 AI 생산 실행에서는 저그가
군락까지 올리고도 1,500초 동안 울트라리스크 동굴을 생략해 토라스크가 없었다.
`AISetStock`만으로 고급 기술 건물 건설이 결정적으로 보장되지 않는 경우였다.

`ultra_ling_bane` 전략에만 군락 완성 후 울트라리스크 동굴 1개를 정상
`AIBuild`로 요청하도록 보강했다. 이는 건물을 즉시 생성하지 않고 내장 AI의 정상
자원·배치·기술 검사를 그대로 거친다. 수정 후 장기 프로브 결과:

```text
t=600s hive=1 ultralisk_cavern=0 torrasque=0
t=700s hive=1 ultralisk_cavern=1 torrasque=0
TORRASQUE_AI_PRODUCTION=PASS
CAMPAIGN_AI_PRODUCTION=PASS
VERIFY_ALL[offline]=PASS (11 checks)
VERIFY_ALL[short-engine]=PASS (2 checks)
VERIFY_ALL[release-engine]=PASS (1 check)
```

토라스크는 700초 출력 직후 다음 관찰 전에 정상 생산되어 PASS 조건을 충족했다.
최종 사용자 맵은 다시 12명/Standard 설정으로 생성했으며 해시는 바뀌지 않았다.

단기 엔진 하네스도 사용자 설정 보존 방식으로 바꿨다. 종전에는 픽스처를
`runtime/custom_ai_settings.json`에 잠시 쓰고 `finally`에서 복원했기 때문에,
하네스 프로세스 자체가 강제 종료되면 복원 코드가 실행되지 않을 수 있었다.
이제 두 전략 프로브는 `SC2TEAM_SETTINGS_FILE`을 지원하고, `verification/verify_all.py`는 별도
임시 JSON 경로만 전달한다. 실제 전후 SHA-256이 동일하고 임시 파일도 남지 않았다.

```text
SETTINGS_HASH_BEFORE=9999C73944C283100F81C9B31F436B6A7C10096A73306F525C8DDF9429B8E823
SETTINGS_HASH_AFTER=9999C73944C283100F81C9B31F436B6A7C10096A73306F525C8DDF9429B8E823
USER_SETTINGS_PRESERVED=PASS
```

`build_runtime_map()` 자체도 검증용 `active_config_file` 경로를 받을 수 있게 했다.
모든 보존 프로브와 오프라인 구조 픽스처가 각자 전용 JSON을 쓰므로 최종 릴리스의
`runtime/custom_ai_active.json`도 더 이상 마지막 프로브 설정으로 바뀌지 않는다.

```text
ACTIVE_CONFIG_PRESERVED_OFFLINE=PASS
USER_AND_ACTIVE_CONFIG_PRESERVED_SHORT_ENGINE=PASS
FINAL_CONFIG=PASS active=12 human=P4 Zerg faction=Standard bridge=True campaign=True
FINAL_MAP_SHA256=A8700616935DB7E6940FB36BC87BB64DE0DABF8EBE8A9F4410C9DB4AF5367FEC
SC2_PROCESSES=0
```

## 40. Custom AI v1.9.0 프로토스 전용 전투 기능

프로토스 전역 진영 프리셋을 외형 전용에서 AI 호환 전투 기능으로 확장했다. 전체
캠페인 종속성을 넣지 않고 `SC2Mapster/SC2GameData` 공개 추출본의 LotV/협동전
레코드를 참고해 `tools/campaign_data/protoss/<faction>/`의 작은 카탈로그 조각만
런타임 맵에 병합한다. 표준 멀티플레이 유닛 ID를 유지하므로 Blizzard 정예 AI의
생산·병력 집계·기본 전술은 계속 작동한다.

구현 범위:

- 아이어: 추적자 ID를 실제 용기병 능력치/무기/모델로 교체하고 점멸을 제거했다.
  광전사는 Solarite Reaper와 전투 중 자동 소용돌이를 사용한다.
- 네라짐: 추적자 점멸 뒤 5초간 보호막을 회복한다. 센추리온의 그림자 돌진/기절과
  학살자의 그림자 포는 자동시전한다. 그림자 포는 AI 사용을 위해 원본의 수동
  설정을 명시적으로 자동시전으로 변경했다.
- 정화자: 선동자는 4초마다 회복되는 3회 충전 점멸을 사용한다. 파수병은 치명
  피해를 자동으로 막고 6.66초간 무적·행동불가 재구성 뒤 완전 회복하며, 이후
  120초 동안 재사용할 수 없다. 표준 광전사 ID를 보존하기 위해 별도 사망체 모프
  대신 같은 유닛의 재구성 상태로 구현했다.
- 탈다림: 학살귀의 점멸 뒤 8초간 원거리 피해가 100% 증가한다. 수행자는 전투 후
  광란의 과부하를 자동시전한다.

위치 지정형 점멸은 원작처럼 수동이다. 대상/전투 조건으로 결정 가능한 소용돌이,
그림자 돌진·포, 광란의 과부하는 `AutoCast`와 `AutoCastOn`을 사용하며, 재구성은
치명 피해 반응 패시브다. 따라서 용기병이 추적자 점멸을 쓰는 문제는 없다.

빌더는 진영별 `AbilData`, `BehaviorData`, `ButtonData`, `EffectData`,
`ValidatorData`, `WeaponData`, `UnitData`, `ActorData`를 선택 병합하고 각 진영의
핵심 연결을 구조 검증한다. `verification/verify_protoss_factions.py`는 단순 생성 검사가 아니라
실제 발동·피해·버프·재구성을 SC2 엔진에서 검증하도록 확장했다.

최종 결과:

```text
VERIFY_ALL[offline]=PASS (11 checks)
PROTOSS_AIUR_DRAGOON=PASS life=120 shields=80
PROTOSS_AIUR_WHIRLWIND_AUTOCAST=PASS damaged_targets=3 total_damage=150
PROTOSS_NERAZIM_BLINK_RESTORE=PASS shield=1->29.75
PROTOSS_NERAZIM_SHADOW_CHARGE_AUTOCAST=PASS distance=5.87695
PROTOSS_NERAZIM_SHADOW_CANNON_AUTOCAST=PASS damage=135
PROTOSS_PURIFIER_MULTI_BLINK=PASS casts=3 distance=6.18809
PROTOSS_PURIFIER_RECONSTRUCTION=PASS state=seen rebuild=6.66s cooldown=120s
PROTOSS_TALDARIM_SLAYER_BLINK=PASS damage_buff=8s
PROTOSS_TALDARIM_FRENZIED_OVERLOAD_AUTOCAST=PASS
PROTOSS_FACTIONS=PASS
VERIFY_ALL[short-engine]=PASS (2 checks)
VERIFY_ALL[release-engine]=PASS (1 check)
```

버전을 `Custom AI v1.9.0`으로 올리고 저장된 12인/Standard 설정으로 최종 맵을
생성했다. 저장 설정과 활성 설정의 해시는 전후 동일했고 SC2 프로세스는 정리됐다.

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.9.0.SC2Map
RELEASE_MAP_BYTES=2944759
RELEASE_MAP_SHA256=201911F91E8C7CA1B7D4BE76AE1867D39418A9214F67778277AB277BF191EE91
SETTINGS_SHA256=9999C73944C283100F81C9B31F436B6A7C10096A73306F525C8DDF9429B8E823
ACTIVE_CONFIG_SHA256=A07A926937DF7171B29A054163D3556A65D865F3849A83F7B68B63F6AE01877F
SC2_PROCESSES=0
```

## 41. Custom AI v1.10.0 프로토스 스킬 순정 이식

40절의 v1.9.0 구현은 중간 단계였으며, 그림자 포를 강제로 자동시전하게 만들고
정화자 재구성을 간소화된 같은-유닛 무적 상태로 바꾼 부분은 최종 요구와 달랐다.
v1.10.0에서 이 개조를 제거하고 공개 추출된 캠페인/협동전 카탈로그의 스킬
레코드와 연결 체계를 원본 형태로 이식했다. 이 절이 40절의 프로토스 스킬 설명을
대체한다.

적용된 스킬 범위:

- 아이어: 용기병은 점멸이 없고, 광전사는 원본 소용돌이와 원본 자동시전 조건을
  사용한다.
- 네라짐: `BlinkShieldRestore`, 그림자 돌진/기절, 수동 그림자 포를 적용했다.
  표준 집정관에는 암흑 집정관의 수동 정신 제어와 혼란을 연결했다.
- 정화자: `BlinkMultiple`, 원본 재구성 사망체/재건 모프 체인, 시간 광선,
  위상 모드/이동 모드를 적용했다.
- 탈다림: `BlinkSlayer`와 `PhaseBlinkDamage`, 광란의 과부하, 목표 고정,
  붉은 역장, 정신 폭발, 사이오닉 구체, 희생을 적용했다.

원본에서 자동시전인 기능만 자동시전으로 남는다. 그림자 포, 정신 제어, 혼란,
위치 지정형 능력 등 원본 수동 스킬은 수동 그대로이며 Blizzard 내장 AI가 이를
사용하지 않아도 별도의 AI용 효과나 자동시전을 만들지 않는다. 일반 공격과 무기
교체 범위도 이번 작업에서 추가 개조하지 않았다.

필요한 호환 조정은 두 가지뿐이다. 내장 AI의 생산·집계 호환을 위해 표준 멀티
유닛 ID를 유지한 채 해당 유닛에 원본 스킬을 연결했고, 캠페인/사령관 메타 진행도
요구 조건 때문에 선택된 스킬 자체가 잠기는 경우에만 그 요구 조건을 해제했다.
스킬 효과, 비용, 쿨다운, 수동/자동시전 성격은 AI 편의를 위해 다시 설계하지
않았다.

최종 엔진 검증:

```text
VERIFY_ALL[offline]=PASS (11 checks)
PROTOSS_FACTION_AIUR=PASS nexus=1 probes=8
PROTOSS_AIUR_DRAGOON=PASS life=120 shields=80
PROTOSS_AIUR_WHIRLWIND_AUTOCAST=PASS damaged_targets=3 total_damage=145
PROTOSS_FACTION_NERAZIM=PASS nexus=1 probes=8
PROTOSS_NERAZIM_BLINK_RESTORE=PASS shield=1->29.75
PROTOSS_NERAZIM_SHADOW_CHARGE_AUTOCAST=PASS distance=5.87695
PROTOSS_NERAZIM_PURE_MANUAL_ABILITIES=PASS shadow_cannon mind_control confusion
PROTOSS_FACTION_PURIFIER=PASS nexus=1 probes=8
PROTOSS_PURIFIER_MULTI_BLINK=PASS casts=3 distance=6.18809
PROTOSS_PURIFIER_PURE_ABILITIES=PASS reconstruction chrono_beam phasing_mode
PROTOSS_FACTION_TALDARIM=PASS nexus=1 probes=8
PROTOSS_TALDARIM_PURE_CASTER_ABILITIES=PASS target_lock force_field mind_blast psi_orb sacrifice
PROTOSS_TALDARIM_SLAYER_BLINK=PASS damage_buff=8s
PROTOSS_TALDARIM_FRENZIED_OVERLOAD_AUTOCAST=PASS
PROTOSS_FACTIONS=PASS
VERIFY_ALL[short-engine]=PASS (2 checks)
VERIFY_ALL[release-engine]=PASS (1 check)
```

최종 릴리스와 설정 보존 상태:

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.0.SC2Map
RELEASE_MAP_BYTES=2944760
RELEASE_MAP_SHA256=CDC6FCC72674D60E1857B7772D66F390526E5E4DAF4801CD4F1F2EFAEEA5CE1C
SETTINGS_SHA256=9999C73944C283100F81C9B31F436B6A7C10096A73306F525C8DDF9429B8E823
ACTIVE_CONFIG_SHA256=A07A926937DF7171B29A054163D3556A65D865F3849A83F7B68B63F6AE01877F
SC2_PROCESSES=0
```

## 42. Custom AI v1.10.1 아이어 용기병 교체 수정

v1.10.0의 아이어 용기병은 표준 `Stalker` ID에 모델·능력치·무기 일부만
덮어썼다. 그 결과 선택 이름은 추적자로 남았고, 추적자 이동/액터 데이터와
용기병 모델이 섞여 보행 애니메이션이 어긋났으며, 용기병 탄환 이동기와 포탑
카탈로그가 없어 실제 공격이 정상 작동하지 않았다.

v1.10.1에서는 Blizzard 멜리 AI의 생산 호환에 필요한 내부 `Stalker` ID만
유지하고 다음 원본 용기병 데이터 체인을 연결했다.

- 용기병 몸체 크기·충돌·가속·`Dragoon` 지상 이동기
- `Dragoon` 포탑과 `DragoonWeapon` 탄환 이동기
- 원본 공격/탄환/충돌 액터 및 공격 애니메이션 이벤트
- 원본 보행 속도, 초상화, 와이어프레임, 아이콘, 워프인/사망 모델과 사운드
- 한국어 `용기병`, 영어 `Dragoon` 유닛·생산 버튼 표시 이름

기존 검증은 생명력 120과 보호막 80만 검사해 이 결함을 놓쳤다. 엔진 하네스에
실제 이동 명령과 공격 이동 명령을 추가했고, 수정된 용기병이 4칸 이동하고 적에게
63 피해를 주는 것을 확인했다. 네 진영 전체 검사도 함께 재통과했다.

```text
PROTOSS_FACTION_AIUR=PASS nexus=1 probes=8
PROTOSS_AIUR_DRAGOON=PASS life=120 shields=80
PROTOSS_AIUR_DRAGOON_MOVE_ATTACK=PASS distance=4 damage=63
PROTOSS_AIUR_WHIRLWIND_AUTOCAST=PASS damaged_targets=3 total_damage=214
PROTOSS_FACTIONS=PASS
VERIFY_ALL[offline]=PASS (11 checks)
VERIFY_ALL[short-engine]=PASS (2 checks)
VERIFY_ALL[release-engine]=PASS (1 check)
RELEASE_ENGINE_SMOKE=PASS players=12 human=P5->runtimeP1
```

현재 저장된 12인 아이어 설정으로 최종 맵을 생성했다. 사람 P5는 런타임 P1
프로토스로 들어갔고 연결된 12명 모두 종족별 본진 1기와 일꾼 8기를 보유했다.

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.1.SC2Map
RELEASE_MAP_BYTES=2952276
RELEASE_MAP_SHA256=8B8DDD6B2750331912F8A3FA52B08ECCA7A61456AF45B47CBAECADBA5A798F5B
SETTINGS_SHA256=9AA7B3CD38D968766D8F94C4D9891E4C20C9B7540BB5587E92245D9975240981
ACTIVE_CONFIG_SHA256=0D6C742C062CB79EA32DBEC3E18093A2C0FAF710E2470DEEC1BEF81B894075B9
SC2_PROCESSES=0
```

## 43. Python 진입점 및 검증 도구 디렉터리 정리

루트에 흩어져 있던 Python 파일을 역할별로 이동했다. 사용자 CMD 진입점은
그대로 루트에 유지하며 기존과 같은 방식으로 실행된다.

- GUI와 로컬 실행기: `app/`
- 검증 하네스와 SC2 엔진 프로브: `verification/`
- 일꾼 인구 보정 단위 테스트: `tests/test_worker_supply_proxy.py`
- 원본 다운로드 압축 파일: `vendor/archives/`
- SC2 Editor 바로가기: 사용자 요청에 따라 루트 유지

각 Python 진입점은 새 위치에서도 프로젝트 루트를 명시적으로 해석하도록
수정했다. `start_custom_ai.cmd`와 `start_pro_bot_test.cmd`, 검증 하네스 내부
프로브 경로, 문서의 실행 명령도 새 경로로 갱신했다.

```text
ROOT_PY_COUNT=0
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
```

## 44. Custom AI v1.10.2 첫 확장 400 미네랄 대기

기존 첫 확장 분기는 생산 시설 조건뿐 아니라 보유 자원 조건도 확인하지 않고
`AIExpand`를 즉시 호출했다. 이 때문에 건설 비용이 없는 시작 시점부터 일꾼이
확장 위치로 이동해 대기했다.

첫 확장의 빠른 운영 의도는 유지하되 다음과 같이 변경했다.

- 본진 1개 상태에서는 전투 유닛 생산을 제한해 확장 자금을 우선 저축한다.
- 현재 미네랄이 400 미만이면 확장 건물 허용·생산 상한·`AIExpand`를 열지 않는다.
- 미네랄 400 이상이 된 경제 루프에서만 두 번째 본진을 허용하고 일꾼을 보낸다.
- 첫 확장은 여전히 생산 건물 완성 조건을 요구하지 않는다.
- 두 번째 이후 확장의 생산 시설 및 자원 조건은 기존대로 유지한다.

빌더의 구조 검증에도 각 활성 AI의 첫 확장 분기에 `>= 400` 조건과 두 번째
본진 스톡 요청이 함께 존재하는지 확인하는 검사를 추가했다. 저장된 12인 아이어
설정으로 v1.10.2 지도를 새로 생성했다. 이번 변경에서는 SC2 엔진을 실행하지
않았으므로 실제 일꾼 출발 시점은 다음 수동 플레이에서 확인해야 한다.

```text
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.2.SC2Map
RELEASE_MAP_BYTES=2951855
RELEASE_MAP_SHA256=BE1C623EEC677A6802CBFD6DF7765EADB13622548F88F3683DCBCBB5FCD21DE2
SETTINGS_SHA256=9AA7B3CD38D968766D8F94C4D9891E4C20C9B7540BB5587E92245D9975240981
ACTIVE_CONFIG_SHA256=0D6C742C062CB79EA32DBEC3E18093A2C0FAF710E2470DEEC1BEF81B894075B9
```

## 45. Custom AI v1.10.3 캠페인 모델 및 순정 토라스크 수정

테란 추가 유닛이 회색 구체 플레이스홀더로 표시되던 문제를 조사했다. 모델 경로만
맵 카탈로그에 기록하고 실제 캠페인 자산 의존성과 원본 부모 액터/모델 레코드를
포함하지 않은 것이 원인이었다. 저그 랩터도 같은 위험이 있었다.

다음 런타임 데이터를 추가했다.

- Liberty Campaign과 Swarm Story Campaign을 Void/VoidMulti보다 먼저 로드하는 자산 의존성
- 프레데터·골리앗·의무관·변형체의 원본 Liberty 액터/모델 부모
- 원본 랩터 모델 부모
- 원본 초상화·와이어프레임·공격 애니메이션을 상속하는 커스텀 자식 액터
- 사람이 직접 확인할 수 있는 `verification/verify_campaign_visuals.py` 시각 프로브

기존 토라스크는 표준 `Ultralisk`에 외형과 치명 피해 무효화를 씌운 뒤, 체력이
2 이하인지 주기적으로 검사해 별도 알로 교체하는 우회 구현이었다. 실제 전투에서
치명 피해 응답이 체력 1 부근에 본체를 남겼고 검사 조건을 벗어나면 본체가 계속
공격했다. 화면의 알도 실제 알이 아니라 무적 토라스크였다.

v1.10.3에서는 이 우회 구현 전체를 제거하고 군단의 심장 원본 레코드를 그대로
이식했다.

- 실제 `HotSTorrasque` 유닛과 `KaiserBlades` 공격 액터
- `TorrasqueDontDie` 치명 피해 응답
- `TorrasqueCorpse` → `TorrasqueChrysalis` → `HotSTorrasque` 원본 변신 체인
- 10초 부활과 원본 부활 제한/타이머 데이터
- 300 미네랄·200 가스·6 인구·울트라리스크 동굴·Larva 1기를 요구하는 AI 구매
- 전략 공격 병력 계산에 `HotSTorrasque=6` 동적 ID 등록

엔진 검증에서 치명 피해 직후 타입 2012 `TorrasqueCorpse`가 관측됐고, 260 게임
루프 뒤 같은 태그가 타입 2011 `HotSTorrasque`, 체력 500으로 돌아왔다. 생성·시체·
부활 전 구간에서 사용 인구는 6으로 유지됐다. 장시간 가속 생산 검사에서는 약
1,000 게임초에 울트라리스크 동굴을 완성한 뒤 순정 토라스크 생산을 확인했다.

```text
CAMPAIGN_DEPENDENCY_NORMAL_START=PASS
CAMPAIGN_ROSTER_CATALOG=PASS
CAMPAIGN_ROSTER_CREATE=PASS
CAMPAIGN_COMBAT_HOTSTORRASQUE=PASS damage=125
CAMPAIGN_COMBAT_SC2TEAMABERRATION=PASS damage=125
CAMPAIGN_COMBAT_SC2TEAMGOLIATH=PASS damage=125
CAMPAIGN_COMBAT_SC2TEAMPREDATOR=PASS damage=125
CAMPAIGN_COMBAT_GOLIATH_AIR=PASS damage=135
CAMPAIGN_COMBAT_MEDIC=PASS life=10->45
TORRASQUE_REVIVE=PASS
TORRASQUE_SUPPLY_STABILITY=PASS
TORRASQUE_AI_PRODUCTION=PASS
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
VERIFY_ALL[short-engine]=PASS (2 checks, 0 failed, 0 not-implemented)
VERIFY_ALL[release-engine]=PASS (1 checks, 0 failed, 0 not-implemented)
RELEASE_ENGINE_SMOKE=PASS players=12 human=P6->runtimeP1
```

자동 Windows 화면 캡처는 연결 메타데이터 오류(`missing sandboxPolicy`) 때문에
사용할 수 없었다. 모델/액터 레코드와 실제 엔진 생성·전투는 검증됐지만, 최종
렌더링 외형은 `start_custom_ai.cmd` 또는 시각 프로브로 한 번 수동 확인해야 한다.

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.3.SC2Map
RELEASE_MAP_BYTES=2961007
RELEASE_MAP_SHA256=BCD5A2604C6ABBDEEAF7173B840494BC4950A29446994AF89E442BF77E3108B9
SETTINGS_SHA256=59E2EE37C21FDE8F52DD0993ACCD676F63E3975BB20C2E71EC4536CC1602D52F
ACTIVE_CONFIG_SHA256=4B60BF594B0B7B2F6F65F7D1C359939CD9325FB3B759C4EB59769BE0CB04713E
SC2_PROCESSES=0
```

## 46. Custom AI v1.10.4 프레데터·랩터 회색 구체 수정

45절의 v1.10.3 이후에도 사용자가 프레데터가 여전히 회색 구체로 표시된다고
보고했다. 45절은 캠페인 자산 의존성과 원본 액터/모델 부모를 추가했지만 실제
원인은 다른 곳에 있었다.

원인은 `CModel`의 `parent` 상속이 `Model` 자산 경로를 물려주지 않는다는 것이다.
`tools/campaign_data/roster/ModelData.xml`에서 변형체·골리앗·의무관은 각자
`<Model>`을 명시했으나, 프레데터와 랩터만 부모(`Predator`, `HotSRaptor`)의
경로를 상속하도록 두었다. 두 부모 모두 올바른 `.m3` 경로를 가지고 있는데도
자식이 회색 구체로 나온 것이 상속이 동작하지 않는다는 직접 증거다.

생성된 v1.10.3 맵의 `Base.SC2Data\GameData\ModelData.xml`을 직접 덤프해
확인했다. 로스터 5개 중 정확히 프레데터와 랩터 2개만 `<Model>`이 비어 있었고
사용자 증상과 일치했다.

```text
v1.10.3: SC2TeamPredatorModel -> (no model!)   SC2TeamRaptorModel -> (no model!)
v1.10.4: SC2TeamPredatorModel -> Assets\Units\Terran\Predator\Predator.m3
         SC2TeamRaptorModel   -> Assets\Units\Zerg\ZerglingEx1A\ZerglingEx1A.m3
```

수정 내용:

- `SC2TeamPredatorModel`에 원본 `Predator.m3` 경로를 명시했다.
- `SC2TeamRaptorModel`에 원본 `ZerglingEx1A.m3`와 `Zergling_SwarmAnims.m3a`
  `RequiredAnims`를 명시했다.
- 빌더 구조 검증에 로스터 `CModel`이 자체 `<Model>` 경로를 갖는지 검사하는
  단계를 추가했다. 명시 경로를 제거한 상태로 오프라인 티어를 돌려 실제로
  `Roster model has no explicit Model asset path: SC2TeamPredatorModel`로
  실패하는 것을 확인했다.

45절의 검증이 이 결함을 놓친 이유는 카탈로그 ID, 디버그 생성, 전투 피해만
검사했고 렌더링되는 모델은 어느 검사도 건드리지 않았기 때문이다. 이는 42절의
용기병 사례와 같은 유형의 공백이다.

```text
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
ROSTER_MODEL_PATHS=5/5 explicit
```

이번 변경은 순수 자산 경로 수정이므로 SC2 엔진 티어는 실행하지 않았다. 실제
렌더링 외형은 `start_custom_ai.cmd`로 사용자가 한 번 육안 확인해야 한다.

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.4.SC2Map
RELEASE_MAP_BYTES=2961049
RELEASE_MAP_SHA256=B791158542173CA0AFBEC9228F7FE482593A18055F2128BD7694C9DD641D5EF4
SETTINGS_SHA256=8710A2EA6E4A450784905782F24D3E8762FEEB36467B385D45A1870D6DBFFA99
ACTIVE_CONFIG_SHA256=E4E90A9AA2F7BB60645838D666427FC9B8C6B9B49176411FA2313AE162437601
```

**46절은 틀렸다. 47절이 이를 대체한다.** 명시 모델 경로는 회색 구체의 원인이
아니었고, v1.10.4를 받은 사용자는 프레데터가 그대로 구체로 보인다고 보고했다.
검증 없이 상관관계만으로 원인을 단정하고 릴리스한 잘못이다.

## 47. Custom AI v1.10.5 캠페인 의존성·액터 바인딩 수정과 렌더 검증

사용자가 v1.10.4에서도 프레데터가 회색 구체이며 단축키·툴팁·공격 정보가 없고
화염차 전환 모드가 활성화되어 있다고 보고했다. 실제 원인은 두 개였고 둘 다
지금까지의 모든 검사를 통과하고 있었다.

### 원인 1: 게임은 DocumentInfo가 아니라 DocumentHeader를 읽는다

`patchCampaignAssetDependencies`는 `DocumentInfo`만 수정했다. 실행 중인 게임은
`DocumentHeader`의 자체 의존성 목록을 읽는다. 따라서 45절이 추가했다고 기록한
캠페인 의존성은 **게임에 도달한 적이 한 번도 없다**. 캠페인 자산이 없으니
프레데터 모델은 로드될 수 없었다.

`DocumentHeader`는 `H2CS` 매직 뒤에 `uint32` 의존성 개수와 그 개수만큼의
NUL 종료 UTF-8 문자열이 이어지는 구조다. `patchDocumentHeaderDependencies`가
이를 병합한다. 효과는 즉시 측정됐다.

```text
DocumentHeader 패치 전: TOTAL_UNIT_TYPES=1081  Predator/Medic/Firebat/Vulture/Wraith=ABSENT
DocumentHeader 패치 후: TOTAL_UNIT_TYPES=2661  전부 PRESENT
```

의존성은 `Liberty (Campaign)` 하나로 충분하다. 저그 로스터 모델은 기본 설치에서
이미 해결된다. `Swarm Story (Campaign)`을 추가하면 `Campaigns/Swarm.SC2Campaign`이
따라 들어와 `FactoryTrain Train20`을 화염차로 재정의하고, 골리앗 구매가 쓰는
슬롯을 조용히 빼앗아 `SC2TeamGoliath`의 `ability_id`가 0이 된다. 런처는 이때
게임을 시작하지 못한다.

### 원인 2: 액터가 구체 유닛 액터를 부모로 삼으면 유닛에 붙지 않는다

`CActorUnit`은 `UnitBirth.##unitName##`으로 자신을 생성하며, 이 토큰은 **선언
시점에 한 번 해석된다.** `Predator` 액터에는 이미 `UnitBirth.Predator`로 굳어
있으므로, 거기서 상속받은 `SC2TeamPredator` 액터는 원본 프레데터가 태어날 때만
반응하고 우리 유닛에는 영원히 붙지 않는다. 그 결과 회색 구체가 된다.
블리자드 자신의 골리앗 변형 `SpartanCompany`도 `GenericUnitBase`를 부모로 쓴다.

로스터 액터 네 개를 모두 제네릭 베이스 상속으로 바꾸고 표현 필드(모델·초상화·
사망·아이콘·와이어프레임)를 각자 명시했다. 이 결함은 프레데터만의 문제가 아니라
**골리앗·의무관·변형체까지 전부** 해당했다. 즉 커스텀 캠페인 유닛은 도입 이래
한 번도 제대로 렌더링된 적이 없다.

### 왜 아무 검사도 못 잡았나

카탈로그 ID·디버그 생성·전투 피해 검사는 회색 구체 상태에서 **전부 통과한다.**
유닛은 존재하고 생성되며 정확한 피해를 준다. 42절의 용기병, 45절의 캠페인 모델,
46절의 잘못된 수정까지 모두 같은 공백이었다. 렌더링을 본 검사가 없었다.

`verification/verify_campaign_render.py`를 추가했다. SC2 렌더 인터페이스를 켜서
실제 화면을 PNG로 저장하고, 블리자드 원본 `Predator`를 함께 배치해 "자산이 없다"와
"우리 배선이 틀렸다"를 구분한다. 이 프로브로 여섯 유닛 모두 실제 모델 렌더링을
육안 확인했다.

빌더 구조 검증에 두 검사를 추가하고, 각각 결함을 되돌려 실제로 실패하는 것을
확인했다.

- 로스터 `CModel`이 자체 `.m3` 경로를 갖는가
- 로스터 `CActorUnit`이 `Generic*` 베이스를 부모로 쓰고 `unitName`을 지정하는가

### 남은 결함

이번 릴리스는 렌더링만 고쳤다. 사용자가 함께 보고한 다음 문제는 그대로다.

- `SC2TeamPredator parent="HellionTank"`, `SC2TeamGoliath parent="Thor"`,
  `SC2TeamMedic parent="Marine"`이라 화염차 전환 모드, 건물 업그레이드 표시,
  공격 정보 누락이 부모에서 상속된다.
- `ButtonData`에 아이콘만 있고 툴팁·단축키 정의가 없다.

캠페인 의존성이 이제 실제로 로드되므로 원본 `Predator`/`Goliath` 레코드를
직접 부모로 쓰는 방향이 가능해졌다. Galaxy 구매 로직과 전략 제어기가 참조하는
ID 범위를 건드리므로 별도 작업으로 남긴다.

```text
CAMPAIGN_ROSTER_CATALOG=PASS
CAMPAIGN_ROSTER_CREATE=PASS
CAMPAIGN_DEPENDENCY_NORMAL_START=PASS
CAMPAIGN_COMBAT=PASS (Torrasque/Aberration/Goliath/Predator/Goliath-air/Medic)
TORRASQUE_REVIVE=PASS
TORRASQUE_SUPPLY_STABILITY=PASS
RENDER=OK 육안 확인: Predator(원본), SC2TeamPredator, SC2TeamGoliath,
          SC2TeamMedic, SC2TeamAberration, HotSTorrasque
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
VERIFY_ALL[short-engine]=PASS (2 checks, 0 failed, 0 not-implemented)
VERIFY_ALL[release-engine]=PASS (1 checks, 0 failed, 0 not-implemented)
SC2_PROCESSES=0
```

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.5.SC2Map
RELEASE_MAP_BYTES=2961977
RELEASE_MAP_SHA256=15DE42FCD070EE6E33185627981BF928F99D4ADB3FCDD18D4D13BC861D3C141A
SETTINGS_SHA256=E2B67805BBA75331456BBEB65DF68CF7C098077DE2170968CF935DBD97F18DB3
ACTIVE_CONFIG_SHA256=0868427A2A63C02DFA3E15324069EB4D1DCB9034312B29A40E05983AC49262C5
```

## 48. Custom AI v1.10.6 멜리 껍데기 제거, 사운드 배선, 단축키·툴팁, 전체화면

47절의 렌더 수정은 유효하다. 이 절은 47절이 "남은 결함"으로 넘긴 것들을 실제로
고친 기록이다.

### 48.1 사용자 보고

```text
프레데터 사운드 안나옴 / 타격 판정이 이상함 — 유닛의 정 중앙을 타격하려고 해서
건물을 때리면 건물 안으로 들어가는 현상 / 전체 창모드 기본 지원 / 신규 유닛 단축키
(메딕 c, 프레데터 p)
```

### 48.2 원인 1: 멜리 유닛을 부모로 삼은 것

로스터 3종은 겉모습만 캠페인 유닛이고 실제로는 멜리 유닛의 파생이었다.

- `SC2TeamPredator parent="HellionTank"`
- `SC2TeamGoliath parent="Thor"`
- `SC2TeamMedic parent="Marine"`

`HellionTank`에는 `<AbilArray Link="MorphToHellion"/>`이 있다. 사용자가 본
"화염차 전환 모드"는 여기서 상속된 것이다. 방어 업그레이드 표시가 어긋난 것도
같은 이유로, 부모의 `LifeArmorName`이 모델과 맞지 않았다.

타격 판정도 여기서 나왔다. 원본 `Predator`는 `Radius 0.625` / `InnerRadius 0.5`인데
로스터는 `Radius 0.5`를 직접 선언했다. 모델은 0.625 크기 그대로이므로 충돌 반경이
모델보다 작았다. `verification/verify_melee_approach.py`로 측정한 값:

```text
구버전  SC2TeamPredator distance=1.949 radius=0.500   (건물 벽 1.812에서 0.137 밖)
원본    Predator        distance=2.190 radius=0.625   (0.378 밖)
```

구버전은 반지름 0.625짜리 모델의 중심이 벽에서 0.137 밖에 섰다. 고양이 몸통이
건물 안으로 약 0.49 들어간다. 사용자가 본 그대로다.

부모를 원본 캠페인 유닛으로 바꾸자 수치가 원본과 완전히 일치했다.

```text
SC2TeamPredator distance=2.190 radius=0.625  drift=0.000 (tolerance 0.1)
```

로스터가 선언하던 생명력·속도·식량·비용은 대부분 원본과 값이 같았으므로 삭제했다.
남긴 것은 이름, 무기 교체, 실제 차이뿐이다. `SC2TeamMedic`은 원본 `heal` 능력과
명령 카드를 그대로 물려받아 `Marine` 부모 때 필요했던 `MedivacHeal` 이식이 사라졌다.
`SC2TeamAberration`은 `Ultralisk` 부모를 유지한다. 캠페인 `InfestedAbomination`은
속도 2로 이 로스터가 원하는 2.95와 맞지 않고, 이미 정상 동작한다.

생산 ability id는 부모 교체 후에도 그대로다: Goliath 609, Predator 610, Medic 579.

### 48.3 원인 2: 사운드는 액터 id로 자동 연결된다

SC2는 유닛 액터의 음성을 **액터 id 규약**으로 연결한다. 액터 `Predator`는 XML 한 줄
없이 `CSound id="Predator_What"`을 찾아낸다. 블리자드의 Predator·Marine·Goliath
액터에 `SoundArray`가 없는 이유가 이것이다. 우리 액터는 `SC2TeamPredator`라서
`SC2TeamPredator_What`을 찾고, 그런 사운드는 없으므로 무음이 된다.

자동 연결은 추측이 아니다. core.sc2mod에 opt-out용
`GenericUnitStandardNoAutoSoundLinks` 형제 클래스가 있고, `GenericUnitSM`은 스토리
유닛을 침묵시키려고 `SoundArray` 각 항목을 빈 문자열로 덮어쓴다. 덮어쓸 필요가
있다는 건 자동으로 채워진다는 뜻이다.

`SoundArray`에 블리자드의 기존 CSound를 명시해 해결했다. 새 사운드 자산은 없다.

이 과정에서 변종도 무음이었다는 것이 드러났다. `UltraliskReady`를 참조하고 있었는데
실제 id는 `Ultralisk_Ready`다. 언더스코어가 빠진 id는 오류가 아니라 침묵이라
아무도 눈치채지 못했다. `Aberration_*` 음성 세트는 Swarm Story에만 있어 쓸 수 없다.

무기 발사·타격음은 `CActorAction`이 담당하며, `effectAttack`은 무기도
`CEffectSet`도 아닌 **`CEffectDamage` 말단**을 가리켜야 한다.

### 48.4 원인 3: CButton에는 단축키도 툴팁도 없다

블리자드의 `CButton id="Marine"`은 아이콘 하나뿐이다. 이름·툴팁·단축키는 전부
문자열 키로 붙는다.

- `Button/Hotkey/<id>` → `<locale>.SC2Data\LocalizedData\GameHotkeys.txt`
- `Button/Name|Tooltip/<id>` → `GameStrings.txt`

빌더는 `GameHotkeys.txt`를 쓴 적이 없다. 아이콘만 있고 글자도 설명도 없던 이유다.
`_NRS`/`_SC1`/`_USD`/`_USDL`은 대체 단축키 프로필이며, 빠뜨리면 기본 프로필에서만
단축키가 동작한다.

배정: 메딕 `C`, 프레데터 `P`, 골리앗 `G`, 변종 `B`, 토라스크 `K`, 랩터 진화 `R`.
각 명령 카드의 순정 단축키와 충돌하지 않는 키를 골랐다.

### 48.5 전체화면

`sc2team/process.py`는 `-displayMode 0`을 고정으로 넘기고 있었다. `fullscreen`
인자를 추가해 런처는 `-displayMode 1`, 검증 프로브는 창 모드를 유지한다.
`CustomLauncherConfig.fullscreen`(기본 True)과 런처 체크박스로 노출했다. 설정
파일에 키가 없으면 True로 로드되므로 기존 설정 파일을 고칠 필요가 없다.

### 48.6 검증에 관하여

`verify_melee_approach.py`를 새로 추가했다. 처음 작성했을 때 피험자를 서로 다른
위치에 배치했는데, 한 위치가 통행 불가라 **거기 놓인 유닛은 종류를 불문하고
실패했다**. 유닛이 아니라 지형을 측정하고 있었던 것이다. 지금은 모든 피험자를
동일한 지점에서 순차 측정하고, 스폰 지점을 떠나지 않은 경우를 별도로 실패시킨다.

허용오차 0.1은 임의값이 아니다. 구버전의 실측 편차 0.241을 실패시키도록 정했다.
느슨하게 하면 보고된 결함이 다시 통과한다.

빌더 검사 두 개를 추가했고 둘 다 역방향 테스트했다.

- 로스터 사운드 id를 vendor 카탈로그와 대조. `Ultralisk_Ready`를 다시
  `UltraliskReady`로 되돌리자 실제로 빌드가 실패했다.
- 단축키·툴팁 문자열 존재 확인. 이 검사는 추가하자마자 토라스크 툴팁 누락을 잡았다.

**사운드는 실제로 들리는지 검증하지 못했다.** 음성 재생을 확인할 수단이 없다.
확인한 것은 참조한 id가 전부 실제 CSound라는 것과 자동 연결 기전의 근거까지다.
실제 소리는 사용자 확인이 필요하다.

```text
MELEE_APPROACH=PASS (SC2TeamPredator drift=0.000 vs 원본 Predator)
CAMPAIGN_ROSTER_CATALOG=PASS  CAMPAIGN_ROSTER_CREATE=PASS
CAMPAIGN_COMBAT=PASS (Torrasque/Aberration/Goliath/Predator/Goliath-air/Medic 10->45)
FULLSCREEN_LAUNCH=PASS game_version=5.0.16.97425
RENDER=OK 육안 확인: Predator(원본), SC2TeamPredator, SC2TeamGoliath, SC2TeamMedic
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
VERIFY_ALL[short-engine]=PASS (2 checks, 0 failed, 0 not-implemented)
RELEASE_ENGINE_SMOKE=PASS
```

```text
RELEASE_MAP=runtime/maps/europe-melee-custom-ai-v1.10.6.SC2Map
RELEASE_MAP_BYTES=2965034
RELEASE_MAP_SHA256=DD9845DF75D4E613B191AABA71095948535C74D32AB8FEB2AFD4494C98689B04
SETTINGS_SHA256=E2B67805BBA75331456BBEB65DF68CF7C098077DE2170968CF935DBD97F18DB3
```

### 48.7 남은 것

- 사운드 실제 재생은 미확인(위 참조).
- `SC2TeamPredator` 명령 카드에 원본의 `RetributionField` 패시브 아이콘이 남아 있다.
  우리 무기의 splash가 사실상 같은 효과라 표시 자체는 거짓이 아니지만 정리 대상이다.
- `SC2TeamGoliath`가 캠페인 `MultilockTargetingSystems`/`ScavengingSystemsMechDeath`
  행동을 상속한다. 해당 업그레이드가 없으면 무해하나 확인되지 않았다.

## 49. 테스트용 런처 (start_custom_ai_test.cmd)

### 49.1 요청

```text
테스트를 좀 편하게 하기 위해서 테스트용 런처를 만들어줘.
자원 무한, 생산 속도 즉시 생산완료를 적용시킨다. 그리고 맵도 다 밝히고
```

### 49.2 측정으로 확인한 SC2 치트의 실제 동작

`DebugGameState` 치트를 그냥 쓰기 전에 실제 게임에서 측정했다. 문서화된 이름과
실제 동작이 달랐다.

- **`all_resources`는 "무한"이 아니라 1회 +5000/+5000 고정 지급이다.** 상태를 켜는
  것이 아니므로 한 번 호출로는 곧 바닥난다. 반복 호출은 **누적**된다
  (10000/10000 → 15000/15000 확인). 그래서 게임 루프에서 재주입한다.
- **`minerals`/`gas` 개별 치트는 신뢰할 수 없다.** 같은 프로브에서 `minerals`는
  +5000 됐지만 `gas`는 전혀 움직이지 않았다. `all_resources`만 쓴다.
- **`fast_build`는 건물은 즉시 완성**시키지만 유닛 생산은 즉시가 아니다. 마린이
  24스텝만에 나왔다(정상 약 400스텝). **약 17배**이지 0초가 아니다.
- **AI의 자원은 API로 관측할 수 없다.** `player_common`은 자기 것만 준다. 따라서
  치트가 AI에게도 걸리는지는 이 방법으로 확인 불가이며, 확인하지 않았다.
  치트는 요청한 Participant(사람)에게 적용되는 것으로 보고 설계했다.

### 49.3 구현

별도 진입점 `start_custom_ai_test.cmd` → `app/play_custom_ai.py --test`.
체크박스가 아니라 별도 런처인 이유는 일반 런처에서 실수로 치트 게임을 시작할 수
없게 하고, 전용 맵 파일을 쓰기 위해서다.

- 참가 직후: `fast_build`, `food`, `show_map`, `all_resources` x2
  - `food`는 즉시 생산이 곧바로 인구에 막히는 것을 푼다.
  - `all_resources` 2회인 이유는 1회가 5050/5000이라 floor(5000)에 걸쳐 첫 tick부터
    재주입이 돌기 때문이다.
- 게임 루프: `min(minerals, vespene) < 5000`이면 `all_resources` 재주입
- 전체 시야: `full_vision=True`를 이 실행에 한해 강제한다. 사용자가 저장한 설정은
  건드리지 않는다. 맵 빌드 타임 설정이므로 **전용 맵 파일**
  `europe-melee-custom-ai-v1.10.6-test.SC2Map`에 빌드한다. 릴리스 맵을 절대
  덮어쓰지 않는다(빌드 후 릴리스 맵 SHA 불변 확인).
- GUI에 제목 `[테스트 모드]`와 주황색 경고 배너를 표시한다.

`protocol.py`에 일반 헬퍼 `debug_game_state(state)`를 추가하고 기존
`debug_show_map`/`debug_control_enemy`를 여기에 위임시켜 중복을 없앴다.

### 49.4 검증

`verification/verify_test_launcher.py`를 추가했다. 이 프로브는 런처 상수를
**복사하지 않고 import**한다. 자체 floor를 들고 있으면 런처가 바뀌어도 프로브는
계속 통과하기 때문이다.

처음 작성했을 때 floor를 10000으로 두었더니 초기 지급 5050/5000이 기준선 아래라
프로브가 실패했다. 실사용에는 문제가 없었겠지만(루프가 곧 채운다) 설계가 어긋난
것이므로 초기 2회 주입 + floor 5000으로 맞췄다.

또한 `debug_create_units`는 자원을 소모하지 않는다(디버그 생성은 무료). 자원을
실제로 소진시켜 재주입을 확인하려던 구간은 아무것도 측정하지 못하므로 삭제하고,
"반복 주입이 누적되는가"를 측정하도록 바꿨다. 무한 자원은 전적으로 이 누적성에
의존한다.

```text
TEST_LAUNCHER_GRANT minerals=10050 vespene=10000
TEST_LAUNCHER_FAST_BUILD structure_progress=1.00
TEST_LAUNCHER_PRODUCTION marine_steps=24 normal~400 speedup~17x
TEST_LAUNCHER_TOPUP 10000/10000 -> 15000/15000
TEST_LAUNCHER=PASS
GUI_SMOKE=PASS (일반/테스트 두 모드 모두 생성)
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
RELEASE_MAP_SHA256 불변=DD9845DF75D4E613B191AABA71095948535C74D32AB8FEB2AFD4494C98689B04
```

### 49.5 한계

- "즉시 생산완료"는 정확히는 약 17배 가속이다. `fast_build`가 SC2가 제공하는
  최대치이며 0초 생산은 불가능하다.
- 치트는 사람 플레이어 기준이다. AI에게도 적용되는지는 확인하지 못했다.

## 50. 테란 병력 빈약 조사 — 부속 건물 가설은 반증됨 (2026-07-17)

### 50.1 배경

사용자 보고: "팩토리는 확장하면서 잘 늘리는데 기술실이나 반응로를 건설을 안 한다.
배럭도 마찬가지." 이어서 "프로토스는 병력 규모가 좀 되는데 테란만 유독 병력이
쓰레기처럼 없는 이유가 아마 이거지 않을까."

가설은 그럴듯했다. 불곰·공성전차·메딕은 전부 기술실을 요구하지만 프로토스 관문
유닛은 부속이 필요 없으므로, 부속이 없으면 테란만 병력이 굶는다는 설명이 된다.
코드 조사도 이를 뒷받침했다: `techlab`/`reactor`/`addon`은 우리 테이블 어디에도
없다. 억제가 아니라 완전한 누락이다.

**이 시점에서 조사자(및 사용자)의 가설을 그대로 수용한 것은 성급했다.** 아래
측정이 가설을 반증했다.

### 50.2 측정

`scratchpad/diag_terran_addons.py` (일회성 진단, 미보존). 사용자의 저장된 구성을
반영해 테란 팀 vs 프로토스 팀으로 16분 스텝 게임을 돌리고, 프로토스를 **대조군**
으로 삼았다 — 관문 유닛은 부속이 필요 없으므로, 테란만 굶는다면 그것이 부속
가설의 증거가 된다.

구성: P1 인간 테란 bio_tank, P2 AI 테란 bio_tank, P3 AI 테란 mech_macro,
P8 AI 프로토스 gateway, P9 AI 프로토스 immortal_colossus. Aiur.

```text
t=360s  TERRAN p2 (bio_tank)  infra={Barracks:4, Factory:3}  addons=NONE
                              army={Marine:8} total=8 techlab_gated=0
        TERRAN p3 (mech_macro) addons={StarportTechLab:1}  Armory 없음
                              army={Hellion:2, Predator:10} total=12
        PROTOSS p5            gateways=4 army={Stalker:8} total=8

t=600s  TERRAN p2  addons={BarracksTechLab:1, FactoryTechLab:2}  Armory:1
                   army={Marine:20, Marauder:7, SiegeTank:8, Medic:5} total=40
        TERRAN p3  Factory:7 Armory:2 addons={BarracksTechLab:1, FactoryTechLab:2,
                   StarportTechLab:1}
                   army={Hellion:6, Predator:13} total=19  ← 골리앗/토르/전차 0
        PROTOSS p4 total=29   PROTOSS p5 total=29

t=960s  TERRAN p2  army={Marine:14, Marauder:14, SiegeTank:10, Medic:6} total=44
        TERRAN p3  army={HellionTank:6, Thor:1, Goliath:25, Predator:20,
                   SiegeTank:8} total=60
        PROTOSS p4 total=46   PROTOSS p5 total=28

SUMMARY 테란 AI 부속 관측 누적:
  BarracksTechLab:72  BarracksReactor:15  FactoryTechLab:142
  FactoryReactor:0    StarportTechLab:49  StarportReactor:0
DIAG=REFUTED
```

### 50.3 결론

- **부속 가설은 반증됐다.** 블리자드 멜리 AI는 우리가 요청하지 않아도 기술실과
  병영 반응로를 스스로 짓는다. 16분 시점 테란 병력(44/60)은 프로토스(46/28)보다
  오히려 많다. 테란이 구조적으로 약하다는 증거는 없다.
- **사용자가 관측한 현상 자체는 정확하다.** p3는 군수공장 9개에 기술실 3개뿐이고
  반응로는 16분 내내 0개였다. 우리는 `AIBuild`로 군수공장을 강제로 불리지만 부속은
  블리자드 AI 재량에 맡겨져 있어 공장 수가 부속을 앞지른다. 맨몸 공장은 화염차와
  프레데터만 만든다.
- **진짜 증상은 "병력이 없다"가 아니라 "mech_macro의 초반 10분이 비어 있다"이다.**
  골리앗·토르는 무기고를, 공성전차는 군수공장 기술실을 기다리는데 멜리 AI가 그것을
  10분쯤에야 짓는다. 그전까지 프레데터와 화염차뿐이다. 사용자 구성은 테란 5명 중
  4명이 mech_macro이므로 체감이 크다.
- `Thor`는 stock 5인데 960초에도 1기다. 원인 미규명.

### 50.4 부수 발견: customValue 21 충돌 (수정함)

`CAMPAIGN_PURCHASE_BY_UNIT`에서 `SC2TeamGoliath`와 `SC2TeamPredator`가 둘 다
`customValue: 21`을 썼다. 이 값은 유닛 저장 슬롯 인덱스이고, 구매 함수는 생산
건물의 해당 슬롯에 쿨다운 만료 시각을 찍는다:

```galaxy
if (sc2team_IsCompletedStructure(currentUnit) &&
    UnitGetCustomValue(currentUnit, customValueIndex) <= now) { ...
    UnitSetCustomValue(currentUnit, customValueIndex, now + cooldown);
```

따라서 둘은 모든 군수공장에서 하나의 쿨다운을 공유하며 서로를 막는다. 나머지
항목은 전부 고유 번호이고, 같은 애벌레를 쓰는 토라스크(19)/아버레이션(20)조차
번호를 나눠 쓰므로 이는 설계가 아니라 복사 실수다. 프레데터를 23으로 옮겼다.

측정으로 격리하지 않았다. 골리앗이 960초에 25기까지 나온 것으로 보아 치명적이지는
않다. 슬롯 26은 토라스크 프로브 마커, 31은 스크립트 제어 타이머가 이미 쓴다.

`verifyPurchaseCooldownSlots()`를 빌더에 추가했다. 가드가 실제로 그 버그를 잡는지
확인했다 — 가드가 통과시키는 가드는 가드가 아니다:

```text
CURRENT_TABLE=NO_ERROR
OLD_COLLIDING_TABLE=ERROR: ... share customValue 21 ...
RESERVED_SLOT_TABLE=ERROR: ... slot 26 is the Torrasque probe marker ...
VERIFY_ALL[offline]=PASS (11 checks, 0 failed, 0 not-implemented)
```

이 수정으로 생성 맵 내용이 바뀌므로 49절에 기록한 v1.10.6 릴리즈 맵 SHA
(DD9845...)는 더 이상 유효하지 않다. 버전은 올리지 않았다. 조사가 끝나지 않았다.

### 50.5 사용자 문의: 테스트 런처에 골리앗 생산 건물이 없다

테스트 런처와 릴리즈 런처의 생산 규칙은 **동일하다.** 테스트 모드는 `full_vision`
만 덮어쓰고 전용 맵 파일에 빌드한다.

골리앗은 `FactoryTrain` `Train20`에 있고 `HaveArmory` 요구조건이 붙어 있다. SC2는
요구조건 미충족 시 버튼을 비활성화가 아니라 숨기므로 "생산 가능한 건물이 없는"
것처럼 보인다. 요구조건 id는 전부 실존을 확인했다(`HaveArmory`,
`HaveAttachedTechLab`, `HaveUltraliskCavern`, `HaveInfestationPit`, `HaveLair` —
모두 `mods/liberty.sc2mod` RequirementData.xml). 버그가 아니다.

프레데터(`Train21`)는 요구조건이 없으므로 군수공장에 항상 보인다. 프레데터는
보이는데 골리앗만 없다면 무기고가 원인이다.

### 50.6 미해결

- mech_macro 초반 10분 공백. 무기고/군수공장 기술실을 앞당기는 것이 후보이며,
  `FORCED_INFRASTRUCTURE_BY_BUILD`(울트라 동굴 선례)가 무기고에는 그대로 쓸 수
  있다. 부속은 일꾼이 놓는 건물이 아니라 건물에 붙으므로 `AIBuild`가 통할지
  불확실하다. vendor 추출본에 `MeleeBuildAI.galaxy`가 없어 정적으로 확인 불가.
  블리자드 소스에서 확인된 유일한 부속 건설 경로는
  `UnitIssueOrder(unit, OrderTargetingPoint(AbilityCommand("FactoryAddOns", n), pos))`
  (LibCOMI.galaxy:20189). 엔진 측정 필요.
- 반응로는 16분간 군수공장/우주공항에 한 번도 붙지 않았다(병영만 15회).
- `Thor` stock 5인데 1기.
- 사용자가 "병력이 쓰레기"라고 느낀 시점(분)을 확인해야 한다. 본 프로브는 7v7
  실시간·mech_macro 4명이라는 사용자 실제 조건을 재현하지 않았다.
