// 유닛 제어(비컨 브리지) 블록: 공격 브로드캐스트(opcode 10/11), 지원 파견,
// 본진 수비, 스크립트 통제/해제, 그리고 파이썬 전략 제어기가 명령을 쏘는
// 투명 마린 비컨. runtime.cjs에서 순수 이동으로 분리했다(산출물 바이트 동일).
//
// 이 모듈이 만드는 Galaxy는 생산/경제 블록(production.cjs)과 전역 변수·
// custom value(30·31)·명단을 일절 공유하지 않는다. sc2team_IssueSupport의
// 호출부도 브리지 자신뿐이다(§60의 재사용 서술은 낡은 것으로 확인, 감사 2026-07-22).

function makeUnitControlBlock(activeSlots, humanRuntimeId, strategyBridge, bridgeProbe, unitControl) {
  // §105: 유닛 제어는 런처 플래그(기본 off). 브리지 프로브 맵은 브리지 자체를
  // 계측하는 맵이므로 플래그와 무관하게 항상 포함한다. 실게임 맵은
  // strategy_bridge(커스텀 레이어 on)에 더해 unit_control까지 켜야 들어간다.
  const bridgeEnabled = bridgeProbe || (strategyBridge && unitControl === true);
  const maintenancePlayers = activeSlots
    .map((_, index) => index + 1)
    .filter((player) => player !== humanRuntimeId);
  const maintenancePlayerCount = Math.max(1, maintenancePlayers.length);
  // Four interleaved phases: release, defense, release, idle.  This preserves
  // a five-game-second release cycle and a ten-game-second defense cycle per
  // player without ever stacking both jobs on the same simulation frame.
  const maintenancePeriod = (10.0 / (maintenancePlayerCount * 4.0)).toFixed(3);
  const maintenancePlayerCases = maintenancePlayers
    .map((player, index) => `    if (cursor == ${index + 1}) { return ${player}; }`)
    .join("\n");
  const attackTargets = activeSlots
    .map((slot, index) => {
      const enemyIndex = activeSlots.findIndex((other) => other.team !== slot.team);
      const enemyPlayer = enemyIndex >= 0 ? enemyIndex + 1 : humanRuntimeId;
      return `    if (player == ${index + 1}) { return PlayerStartLocation(${enemyPlayer}); }`;
    })
    .join("\n");
  const pauseAI = bridgeProbe ? "\n    AITimePause(true);" : "";
  // §70: 수비 트리거는 실게임에서만 돈다. 브리지 프로브는 스크립트 통제
  // 유닛 수를 계측하므로 수비가 도장을 찍으면 측정이 오염된다.
  const defenseEnabled = strategyBridge && !bridgeProbe;
  // §70: 빌드 시점에 아는 팀 배치를 Galaxy 리터럴로 굽는다. 수비 트리거가
  // 동맹 판별 네이티브 없이 적을 가려낼 수 있게 한다.
  const playerTeams = activeSlots
    .map((slot, index) => `    if (player == ${index + 1}) { return ${slot.team}; }`)
    .join("\n");
  // §70: 사람 슬롯 유닛은 절대 지휘하지 않는다 — 수비 대상에서 제외.
  const bridgeDeclarations = bridgeEnabled
    ? `trigger gt_sc2team_CommandBridge;
trigger gt_sc2team_Maintenance;
unit gv_sc2team_CommandBeacon;
timer gv_sc2team_ControlTimer;
// §99: 플레이어별 명단으로 나눠 한 발화가 한 AI 병력만 훑게 한다. 종전의
// 단일 그룹은 5게임초마다 모든 AI의 통제 병력을 한 프레임에 순회했다.
unitgroup[16] gv_sc2team_ControlledUnits;
int gv_sc2team_ControlReleaseCursor;
int gv_sc2team_HomeDefenseCursor;
int gv_sc2team_MaintenancePhase;

bool sc2team_IsGroundArmyUnit (unit candidate) {
    // §105.5(A2): 라바는 생산 자원이지 병력이 아니다. 속도 0.5625/지상 평면이라
    // 아래 판정을 통과해 공격·지원·수비 세 채널이 라바에 통제 도장을 찍고
    // homeCount를 부풀리고 있었다. Blizzard 자신도 유닛 순회에서 Larva를 명시
    // 제외한다(LibCOMU.galaxy:1532). Egg는 속도 0이라 이미 걸러진다.
    if (UnitGetType(candidate) == "SCV" ||
        UnitGetType(candidate) == "Probe" ||
        UnitGetType(candidate) == "Drone" ||
        UnitGetType(candidate) == "MULE" ||
        UnitGetType(candidate) == "Larva" ||
        UnitGetType(candidate) == "Queen") {
        return false;
    }
    return UnitTestPlane(candidate, c_planeGround) &&
        UnitGetPropertyFixed(candidate, c_unitPropMovementSpeed, c_unitPropCurrent) > 0.0;
}

void sc2team_ControlForSeconds (unit controlledUnit, fixed duration) {
    int controlledPlayer;

    AISetUnitScriptControlled(controlledUnit, true);
    UnitSetCustomValue(
        controlledUnit,
        31,
        TimerGetElapsed(gv_sc2team_ControlTimer) + duration
    );
    controlledPlayer = UnitGetOwner(controlledUnit);
    // 플레이어별 명단에 올려 해제 작업을 라운드로빈으로 분산한다.
    if (controlledPlayer >= 1 && controlledPlayer <= 15 &&
        !UnitGroupHasUnit(gv_sc2team_ControlledUnits[controlledPlayer], controlledUnit)) {
        UnitGroupAdd(gv_sc2team_ControlledUnits[controlledPlayer], controlledUnit);
    }
}

int sc2team_MaintenancePlayer (int cursor) {
${maintenancePlayerCases}
    return 0;
}

void sc2team_IssueGroundArmyOrder (unit orderedUnit, point destination) {
    if (UnitGetType(orderedUnit) == "SC2TeamMedic") {
        UnitIssueOrder(
            orderedUnit,
            OrderTargetingPoint(AbilityCommand("move", 0), destination),
            c_orderQueueReplace
        );
    }
    else {
        UnitIssueOrder(
            orderedUnit,
            OrderTargetingPoint(AbilityCommand("attack", 0), destination),
            c_orderQueueReplace
        );
    }
}

// §70: 유닛 저장칸 30 = 수비·지원 임무 보류 만료 시각(19~23·26·31은 사용 중).
// 임무 중인 유닛은 45초 주기 공격 브로드캐스트가 건너뛴다 — 이 보호가 없으면
// 출격 명령이 지원 행군과 수비 요격을 매번 덮어써 둘 다 무효가 된다
// (사용자 실관측: 팀이 죽어가도 아무도 안 움직임).
void sc2team_HoldMission (unit missionUnit, fixed duration) {
    UnitSetCustomValue(
        missionUnit,
        30,
        TimerGetElapsed(gv_sc2team_ControlTimer) + duration
    );
}

bool sc2team_MissionHeld (unit candidate) {
    return UnitGetCustomValue(candidate, 30) > TimerGetElapsed(gv_sc2team_ControlTimer);
}

bool sc2team_IsTownHallUnit (unit candidate) {
    string hallType = UnitGetType(candidate);
    return hallType == "CommandCenter" || hallType == "OrbitalCommand" ||
        hallType == "PlanetaryFortress" || hallType == "Nexus" ||
        hallType == "Hatchery" || hallType == "Lair" || hallType == "Hive";
}

int sc2team_PlayerTeam (int player) {
${playerTeams}
    return 0;
}

// §70: 이 맵의 멜레 AI 모듈은 여럿이 죽어 있고(연구·확장), 스크립트 통제 중
// 유닛은 살아 있는 모듈도 못 움직이므로 본진 수비를 트리거가 직접 한다.
// 10초마다 완성 타운홀 반경 25 안의 적 지상 병력을 세고, 3기 이상이면 본진
// 반경 40 안의 병력에게 요격을 명령한다. 적이 본진 병력의 2배 이상이면
// (괴멸적 공격) 전군을 그 지점으로 회군시킨다. 틱당 한 기지만 처리한다.
void sc2team_DefendHome (int player) {
    unitgroup ownUnits;
    unitgroup nearbyUnits;
    unit currentUnit;
    unit hallUnit;
    point hallPoint;
    point threatPoint;
    int unitIndex;
    int nearbyIndex;
    int defenderIndex;
    int threatCount;
    int homeCount;
    int myTeam;
    int ownerTeam;
    bool devastating;

    myTeam = sc2team_PlayerTeam(player);
    if (myTeam < 1) {
        return;
    }
    ownUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(ownUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        hallUnit = UnitGroupUnitFromEnd(ownUnits, unitIndex);
        if (hallUnit == null) {
            break;
        }
        if (!sc2team_IsTownHallUnit(hallUnit) ||
            libNtve_gf_UnitIsUnderConstruction(hallUnit)) {
            continue;
        }
        hallPoint = UnitGetPosition(hallUnit);
        threatCount = 0;
        threatPoint = null;
        nearbyUnits = UnitGroup(null, c_playerAny, RegionCircle(hallPoint, 25.0), UnitFilter(0, 0, 0, 0), 0);
        nearbyIndex = UnitGroupCount(nearbyUnits, c_unitCountAlive);
        for (;; nearbyIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(nearbyUnits, nearbyIndex);
            if (currentUnit == null) {
                break;
            }
            ownerTeam = sc2team_PlayerTeam(UnitGetOwner(currentUnit));
            if (ownerTeam >= 1 && ownerTeam != myTeam &&
                currentUnit != gv_sc2team_CommandBeacon &&
                sc2team_IsGroundArmyUnit(currentUnit)) {
                threatCount += 1;
                threatPoint = UnitGetPosition(currentUnit);
            }
        }
        if (threatCount < 3) {
            continue;
        }
        homeCount = 0;
        defenderIndex = UnitGroupCount(ownUnits, c_unitCountAlive);
        for (;; defenderIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(ownUnits, defenderIndex);
            if (currentUnit == null) {
                break;
            }
            if (sc2team_IsGroundArmyUnit(currentUnit) &&
                DistanceBetweenPoints(UnitGetPosition(currentUnit), hallPoint) <= 40.0) {
                homeCount += 1;
            }
        }
        // §105.5(A3): 전군 회군은 "괴멸적"일 때만 — homeCount == 0 이면 종전
        // 조건(threat >= home*2)이 무조건 참이라 원거리 3기가 전군을 무기한
        // 본진에 묶었다. 타운홀이 실제로 맞기 시작했을 때만 괴멸적으로 본다.
        // 최대 생명력은 별도 속성 id(c_unitPropLifeMax)다 — 존재하지 않는
        // c_unitPropMax를 쓰면 스크립트 전체가 컴파일 실패로 침묵 사망한다
        // (§105.5 실측: 두 엔진 프로브가 비컨 0개로 죽었다).
        devastating = threatCount >= (homeCount * 2) &&
            UnitGetPropertyFixed(hallUnit, c_unitPropLife, c_unitPropCurrent) <
            UnitGetPropertyFixed(hallUnit, c_unitPropLifeMax, c_unitPropCurrent);
        defenderIndex = UnitGroupCount(ownUnits, c_unitCountAlive);
        for (;; defenderIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(ownUnits, defenderIndex);
            if (currentUnit == null) {
                break;
            }
            if (!sc2team_IsGroundArmyUnit(currentUnit)) {
                continue;
            }
            // 반경 40 지역 요격은 무조건(재스탬프가 필요한 로컬 방어).
            if (DistanceBetweenPoints(UnitGetPosition(currentUnit), hallPoint) <= 40.0) {
                sc2team_ControlForSeconds(currentUnit, 30.0);
                sc2team_HoldMission(currentUnit, 30.0);
                sc2team_IssueGroundArmyOrder(currentUnit, threatPoint);
            }
            // §105.5(A3): 원거리 전군 회군은 이미 우리가 통제 중인 병력만,
            // 다른 임무(지원 행군·타 기지 방어) 중이 아닐 때만. 갓 생산돼
            // 밀레 AI 손에 있는 병력은 건드리지 않는다.
            else if (devastating && AIIsScriptControlled(currentUnit) &&
                !sc2team_MissionHeld(currentUnit)) {
                sc2team_ControlForSeconds(currentUnit, 30.0);
                sc2team_HoldMission(currentUnit, 30.0);
                sc2team_IssueGroundArmyOrder(currentUnit, threatPoint);
            }
        }
        return;
    }
}

bool sc2team_HomeDefense_Func (bool testConds, bool runActions) {
    int player;

    if (!runActions) {
        return true;
    }
    gv_sc2team_HomeDefenseCursor += 1;
    if (gv_sc2team_HomeDefenseCursor > ${maintenancePlayerCount}) {
        gv_sc2team_HomeDefenseCursor = 1;
    }
    player = sc2team_MaintenancePlayer(gv_sc2team_HomeDefenseCursor);
    if (player > 0) {
        sc2team_DefendHome(player);
    }
    return true;
}

void sc2team_IssueSupport (int player, point destination) {
    unitgroup targetUnits;
    unit currentUnit;
    int unitIndex;
    int eligibleCount = 0;
    int supportLimit;
    int sent = 0;

    targetUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(targetUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        // §105.5(A4): 본진 방어 중(cv30)인 병력은 지원 차출에서 제외 —
        // opcode 10/11 공격 브로드캐스트와 정확히 같은 가드. 카운트도 같은
        // 조건으로 세므로 "절반" 비율은 가용 병력 기준으로 유지된다.
        if (sc2team_IsGroundArmyUnit(currentUnit) &&
            !sc2team_MissionHeld(currentUnit)) {
            eligibleCount += 1;
        }
    }
    supportLimit = (eligibleCount + 1) / 2;
    if (supportLimit > 30) {
        supportLimit = 30;
    }
    unitIndex = UnitGroupCount(targetUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
        if (currentUnit == null || sent >= supportLimit) {
            break;
        }
        if (sc2team_IsGroundArmyUnit(currentUnit) &&
            !sc2team_MissionHeld(currentUnit)) {
            sc2team_ControlForSeconds(currentUnit, 45.0);
            sc2team_HoldMission(currentUnit, 45.0);
            sc2team_IssueGroundArmyOrder(currentUnit, destination);
            sent += 1;
        }
    }
}

// §99: 종전에는 5게임초마다 모든 플레이어의 통제 명단을 한꺼번에 훑었다.
// 이제 한 발화에는 한 플레이어만 처리하고, 전체 순환은 기존과 같은 5게임초다.
//
// 삭제는 순회 중에 하지 않는다. 인덱스가 밀려 건너뛰는 유닛이 생기고, 그러면
// 그 유닛은 영원히 스크립트 제어에 묶인 채 멜레 AI 손을 벗어난다. 만료 목록을
// 먼저 모으고 두 번째 패스에서 지운다.
bool sc2team_ControlRelease_Func (bool testConds, bool runActions) {
    unitgroup expired;
    unit currentUnit;
    int unitIndex;
    fixed now;
    fixed releaseAt;
    int player;

    if (!runActions) {
        return true;
    }
    gv_sc2team_ControlReleaseCursor += 1;
    if (gv_sc2team_ControlReleaseCursor > ${maintenancePlayerCount}) {
        gv_sc2team_ControlReleaseCursor = 1;
    }
    player = sc2team_MaintenancePlayer(gv_sc2team_ControlReleaseCursor);
    if (player <= 0) {
        return true;
    }
    now = TimerGetElapsed(gv_sc2team_ControlTimer);
    expired = UnitGroupEmpty();
    unitIndex = UnitGroupCount(gv_sc2team_ControlledUnits[player], c_unitCountAll);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(gv_sc2team_ControlledUnits[player], unitIndex);
        if (currentUnit == null) {
            break;
        }
        releaseAt = UnitGetCustomValue(currentUnit, 31);
        // 죽었거나(명단 정리) 이미 해제됐거나 기한이 지난 유닛.
        if (!UnitIsAlive(currentUnit) || releaseAt <= 0.0 || releaseAt <= now) {
            UnitGroupAdd(expired, currentUnit);
        }
    }
    unitIndex = UnitGroupCount(expired, c_unitCountAll);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(expired, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (UnitIsAlive(currentUnit)) {
            AISetUnitScriptControlled(currentUnit, false);
            UnitSetCustomValue(currentUnit, 31, 0.0);
        }
        UnitGroupRemove(gv_sc2team_ControlledUnits[player], currentUnit);
    }
    return true;
}

// 해제와 수비를 같은 프레임에 실행하지 않는다. 4단계 중 해제는 두 번,
// 수비는 한 번 실행하므로 플레이어별 주기는 각각 5초와 10초로 유지된다.
bool sc2team_Maintenance_Func (bool testConds, bool runActions) {
    if (!runActions) {
        return true;
    }
    gv_sc2team_MaintenancePhase += 1;
    if (gv_sc2team_MaintenancePhase > 4) {
        gv_sc2team_MaintenancePhase = 1;
    }
    if (gv_sc2team_MaintenancePhase == 1 || gv_sc2team_MaintenancePhase == 3) {
        sc2team_ControlRelease_Func(false, true);
    }
    else if (gv_sc2team_MaintenancePhase == 2 && ${defenseEnabled ? "true" : "false"}) {
        sc2team_HomeDefense_Func(false, true);
    }
    return true;
}

point sc2team_AttackDestination (int player) {
${attackTargets}
    return PlayerStartLocation(${humanRuntimeId});
}

// 대상 플레이어의 현재 위치를 공격 목적지로 해석한다: 완성 타운홀 우선,
// 없으면 잔존 유닛, 그마저 없으면 null(호출부에서 정적 목적지로 폴백).
// 완성 검사는 경제 규칙 블록의 헬퍼에 기대지 않도록 인라인한다(브리지 프로브
// 맵에는 그 블록이 없다).
point sc2team_EnemyAttackPoint (int enemyPlayer) {
    unitgroup enemyUnits;
    unit currentUnit;
    unit fallbackUnit;
    int unitIndex;
    string currentType;

    fallbackUnit = null;
    enemyUnits = UnitGroup(null, enemyPlayer, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(enemyUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(enemyUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (fallbackUnit == null) {
            fallbackUnit = currentUnit;
        }
        currentType = UnitGetType(currentUnit);
        if (!libNtve_gf_UnitIsUnderConstruction(currentUnit) &&
            (currentType == "CommandCenter" || currentType == "OrbitalCommand" ||
             currentType == "PlanetaryFortress" || currentType == "Nexus" ||
             currentType == "Hatchery" || currentType == "Lair" ||
             currentType == "Hive")) {
            return UnitGetPosition(currentUnit);
        }
    }
    if (fallbackUnit != null) {
        return UnitGetPosition(fallbackUnit);
    }
    return null;
}

bool sc2team_CommandBridge_Func (bool testConds, bool runActions) {
    point commandPoint;
    point destination;
    unitgroup targetUnits;
    unit currentUnit;
    int opcode;
    int targetPlayer;
    int unitIndex;
    int supportPlayer;
    int destinationX;
    int scriptCount;
    int enemyTarget;
    fixed encodedX;
    fixed encodedY;

    if (EventUnit() != gv_sc2team_CommandBeacon) {
        return true;
    }
    commandPoint = OrderGetTargetPoint(EventUnitOrder());
    if (commandPoint == null) {
        return true;
    }
    encodedX = PointGetX(commandPoint);
    destinationX = FixedToInt(encodedX);
    supportPlayer = FixedToInt(((encodedX - IntToFixed(destinationX)) * 100.0) + 0.5);
    if (supportPlayer >= 1 && supportPlayer <= 14) {
        destination = Point(IntToFixed(destinationX), PointGetY(commandPoint));
        UnitSetPosition(gv_sc2team_CommandBeacon, PlayerStartLocation(1), false);
        sc2team_IssueSupport(supportPlayer, destination);
        return true;
    }
    opcode = destinationX - 100;
    encodedY = PointGetY(commandPoint);
    targetPlayer = FixedToInt(encodedY) - 100;
    // Y 소수부(1/100 자리)의 추가 정수. 지원 인코딩의 X 소수부 복호와 같은 기법.
    enemyTarget = FixedToInt(((encodedY - IntToFixed(FixedToInt(encodedY))) * 100.0) + 0.5);
    UnitSetPosition(gv_sc2team_CommandBeacon, PlayerStartLocation(1), false);
    if (opcode == 1 && targetPlayer >= 1 && targetPlayer <= 14) {
        PlayerModifyPropertyInt(targetPlayer, c_playerPropMinerals, c_playerPropOperAdd, 123);
        UnitCreate(1, "Marine", c_unitCreateIgnorePlacement, targetPlayer, PlayerStartLocation(targetPlayer), 0.0);
    }
    if (opcode == 2 && targetPlayer >= 1 && targetPlayer <= 14) {
        destination = PlayerStartLocation(1);
        targetUnits = UnitGroup(null, targetPlayer, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
        unitIndex = UnitGroupCount(targetUnits, c_unitCountAll);
        for (;; unitIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
            if (currentUnit == null) {
                break;
            }
            if (UnitGetType(currentUnit) == "SCV" ||
                UnitGetType(currentUnit) == "Probe" ||
                UnitGetType(currentUnit) == "Drone") {
                AISetUnitScriptControlled(currentUnit, true);
                UnitIssueOrder(
                    currentUnit,
                    OrderTargetingPoint(AbilityCommand("attack", 0), destination),
                    c_orderQueueReplace
                );
            }
        }
    }
    if (opcode == 3 && targetPlayer >= 1 && targetPlayer <= 14) {
        scriptCount = 0;
        targetUnits = UnitGroup(null, targetPlayer, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
        unitIndex = UnitGroupCount(targetUnits, c_unitCountAlive);
        for (;; unitIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
            if (currentUnit == null) {
                break;
            }
            if (AIIsScriptControlled(currentUnit) &&
                UnitGetCustomValue(currentUnit, 31) > 0.0) {
                scriptCount += 1;
            }
        }
        UnitCreate(scriptCount, "Marine", c_unitCreateIgnorePlacement, 1, PlayerStartLocation(1), 0.0);
    }
    // §105.5(A1): 통제 시간 20초 < 파이썬 재출격 주기 45초. 종전엔 둘 다
    // 45초라 만료 전에 다음 출격이 통제를 갱신해 "45초 뒤 밀레 AI에게 반환"
    // (system-overview.md의 약속)이 중후반엔 한 번도 일어나지 않았다(§70.1
    // 실측: "병력이 사실상 항상 스크립트 통제 상태"). 이제 매 주기 20~25
    // 게임초는 밀레 AI가 전군을 온전히 지휘한다 — 우리 몫은 "지금, 저 약한
    // 적에게 출발"이라는 개시 신호뿐이다. verify()가 두 상수의 부등식을
    // 파이썬 소스와 대조해 고정한다(다시 같아지면 빌드 실패).
    if (opcode == 10 && targetPlayer >= 1 && targetPlayer <= 14) {
        destination = sc2team_AttackDestination(targetPlayer);
        targetUnits = UnitGroup(null, targetPlayer, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
        unitIndex = UnitGroupCount(targetUnits, c_unitCountAlive);
        for (;; unitIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
            if (currentUnit == null) {
                break;
            }
            if (sc2team_IsGroundArmyUnit(currentUnit) &&
                !sc2team_MissionHeld(currentUnit)) {
                sc2team_ControlForSeconds(currentUnit, 20.0);
                sc2team_IssueGroundArmyOrder(currentUnit, destination);
            }
        }
    }
    if (opcode == 11 && targetPlayer >= 1 && targetPlayer <= 14 &&
        enemyTarget >= 1 && enemyTarget <= 14) {
        destination = sc2team_EnemyAttackPoint(enemyTarget);
        if (destination == null) {
            destination = sc2team_AttackDestination(targetPlayer);
        }
        targetUnits = UnitGroup(null, targetPlayer, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
        unitIndex = UnitGroupCount(targetUnits, c_unitCountAlive);
        for (;; unitIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
            if (currentUnit == null) {
                break;
            }
            if (sc2team_IsGroundArmyUnit(currentUnit) &&
                !sc2team_MissionHeld(currentUnit)) {
                sc2team_ControlForSeconds(currentUnit, 20.0);
                sc2team_IssueGroundArmyOrder(currentUnit, destination);
            }
        }
    }
    return true;
}

void sc2team_InitializeCommandBridge () {
    int initPlayer;
${pauseAI}
    gv_sc2team_ControlTimer = TimerCreate();
    TimerStart(gv_sc2team_ControlTimer, 1000000.0, false, c_timeGame);
    for (initPlayer = 1; initPlayer <= 15; initPlayer += 1) {
        gv_sc2team_ControlledUnits[initPlayer] = UnitGroupEmpty();
    }
    gv_sc2team_ControlReleaseCursor = 0;
    gv_sc2team_HomeDefenseCursor = 0;
    gv_sc2team_MaintenancePhase = 0;
    gt_sc2team_Maintenance = TriggerCreate("sc2team_Maintenance_Func");
    TriggerAddEventTimePeriodic(gt_sc2team_Maintenance, ${maintenancePeriod}, c_timeGame);
    UnitCreate(1, "Marine", c_unitCreateIgnorePlacement, 1, PlayerStartLocation(1), 0.0);
    gv_sc2team_CommandBeacon = UnitLastCreated();
    libNtve_gf_MakeUnitInvulnerable(gv_sc2team_CommandBeacon, true);
    UnitSetState(gv_sc2team_CommandBeacon, c_unitStateUsingSupply, false);
    ActorSend(
        libNtve_gf_MainActorofUnit(gv_sc2team_CommandBeacon),
        libNtve_gf_SetOpacity(0.0, 0.0)
    );
    ActorSend(
        libNtve_gf_MainActorofUnit(gv_sc2team_CommandBeacon),
        libNtve_gf_SetVisibility(false)
    );
    gt_sc2team_CommandBridge = TriggerCreate("sc2team_CommandBridge_Func");
    TriggerAddEventUnitOrder(gt_sc2team_CommandBridge, null, AbilityCommand("move", 0));
}

`
    : "";
  const bridgeInit = bridgeEnabled ? "\n    sc2team_InitializeCommandBridge();" : "";
  return { bridgeDeclarations, bridgeInit };
}

module.exports = {
  makeUnitControlBlock,
};
