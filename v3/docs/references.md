# V3 스크립트 레퍼런스

## 업스트림과 정책 소스

- `v3/ai/manifest.json`: 고정 upstream commit, 경로, SHA-256
- `v3/ai/upstream/`: 원본 AI 54개
- `v3/ai/overlay-manifest.json`: overlay와 생성 root 해시
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/TerranBionic.galaxy`
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/TerranMechanic.galaxy`
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/ProtossGateway.galaxy`
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/ProtossGatewayRobo.galaxy`
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/ZergRoachHydraUltra.galaxy`
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/ZergLingBaneUltra.galaxy`

## 조립과 실행

- `v3/tools/build_v3_ai_mod.cjs`: upstream+overlay 검증 및 SC2Mod 생성
- `v3/tools/v3_ai_layout.cjs`: 종족 root hook 생성 규칙
- `v3/tools/patch_v3_ai.cjs`: mod dependency와 build ID의 MapScript 삽입
- `v3/sc2team_v3/config.py`: build ID와 종족별 선택지
- `v3/sc2team_v3/runtime.py`: 슬롯 매핑과 맵 빌드
- `app/play_custom_ai_v3.py`: 런처
- `v3/verification/probe_v3_ground_builds.py`: 실제 SC2 3분 간격 표본

## Galaxy 주의점

- 지역 변수는 실행문보다 먼저 선언한다.
- 기본 AI 상수 중 MapScript에서 노출되지 않는 값은 검증된 native 숫자를 쓴다.
- `AISetStockUnitNext`는 앞 목표가 뒤 예산을 막을 수 있으므로 순서가 중요하다.
- 첫 확장은 `AIExpand`로 등록하고 `AIIsExpandingOrHasExpanded`로 중복을 막는다.
- 캠페인 유닛은 catalog 외에도 maker/producer ability 연결이 필요하다.
- V3는 Stock 목표만 제공하며 `AIBuild`, `AITrain`, `AIResearch`, 생산 목적
  `UnitIssueOrder`를 사용하지 않는다.
