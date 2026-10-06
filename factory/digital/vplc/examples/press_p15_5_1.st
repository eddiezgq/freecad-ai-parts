(* 程序 15.5.1  压装工位：加上异常处理——动作超时、传感器冲突、急停与恢复 *)
TYPE E_Press : (INIT, HOMING, IDLE, CLAMPING, PRESSING, RETURNING, UNCLAMPING, FAULT, ESTOP); END_TYPE

PROGRAM Main
  VAR
    state : E_Press := INIT;
    prev : E_Press := INIT;    (* 上一次扫描的状态：状态一变，计时重新开始 *)
    tState : TON;              (* 本状态已经停留的时间 *)
    maxTime : TIME;            (* 本状态允许停留的最长时间 *)
    faultCode : INT;               (* 故障代码：0 无；1 夹紧超时；2 压装超时；3 回程超时；4 松开超时；5 回原点超时；9 传感器冲突 *)
    clampHold : BOOL;          (* 进入故障或急停时夹具是否夹着：保持原样 *)
    auto, go, jog : BOOL;
    rStep, rReset : R_TRIG;
    tTwoHand : TON;
    force, peak : REAL;
    resOk, resNok : BOOL;
  END_VAR

  force := INT_TO_REAL(AI_Force) * 10.0 / 27648.0;
  tTwoHand(IN := S_Hand1 OR S_Hand2, PT := T#500ms);
  rStep(CLK := S_Step);
  rReset(CLK := S_Reset);
  auto := S_Auto;
  go := auto OR rStep.Q;

  (* 1. 急停与传感器冲突：任何状态下都优先 *)
  IF NOT S_EStop AND state <> ESTOP THEN
    clampHold := Y_Clamp; state := ESTOP;
  ELSIF ((B_Clamped AND B_Unclamped) OR (B_PressUp AND B_PressDown)) AND state <> FAULT AND state <> ESTOP THEN
    clampHold := Y_Clamp; faultCode := 9; state := FAULT;
  END_IF;

  (* 2. 状态时限：自动方式和回原点时才计时（单步时等的是人） *)
  CASE state OF
    CLAMPING, UNCLAMPING: maxTime := T#1s;
    PRESSING: maxTime := T#4s;
    RETURNING: maxTime := T#5s;
    HOMING: maxTime := T#5s;
  ELSE
    maxTime := T#1h;
  END_CASE;
  tState(IN := state = prev AND (auto OR state = HOMING), PT := maxTime);
  prev := state;

  (* 3. 转移 *)
  CASE state OF
    INIT:
      IF rReset.Q THEN state := HOMING; END_IF;
    HOMING:
      IF B_PressUp AND B_Unclamped THEN state := IDLE;
      ELSIF tState.Q THEN clampHold := FALSE; faultCode := 5; state := FAULT; END_IF;
    IDLE:
      IF rReset.Q THEN
        state := HOMING;
      ELSIF B_Part AND B_PressUp AND B_Unclamped AND S_LC
            AND ((auto AND S_Hand1 AND S_Hand2 AND NOT tTwoHand.Q) OR (NOT auto AND rStep.Q)) THEN
        resOk := FALSE; resNok := FALSE; peak := 0.0;
        state := CLAMPING;
      ELSIF NOT auto AND (S_JogClamp OR S_JogDown OR S_JogUp) THEN
        state := INIT;                    (* 点动过：位置不再确定，再启动前要回原点 *)
      END_IF;
    CLAMPING:
      IF go AND B_Clamped THEN state := PRESSING;
      ELSIF tState.Q THEN clampHold := TRUE; faultCode := 1; state := FAULT; END_IF;
    PRESSING:
      peak := MAX(peak, force);
      IF force > 8.0 THEN
        resNok := TRUE; state := RETURNING;
      ELSIF go AND B_PressDown THEN
        resOk := peak >= 4.0 AND peak <= 7.0; resNok := NOT resOk;
        state := RETURNING;
      ELSIF auto AND NOT (S_Hand1 AND S_Hand2 AND S_LC) THEN
        resNok := TRUE; state := RETURNING;
      ELSIF tState.Q THEN clampHold := TRUE; faultCode := 2; state := FAULT; END_IF;
    RETURNING:
      IF go AND B_PressUp THEN state := UNCLAMPING;
      ELSIF tState.Q THEN clampHold := TRUE; faultCode := 3; state := FAULT; END_IF;
    UNCLAMPING:
      IF go AND B_Unclamped THEN state := IDLE;
      ELSIF tState.Q THEN clampHold := FALSE; faultCode := 4; state := FAULT; END_IF;
    FAULT:                                (* 停在原地，等人看清原因、按复位 *)
      IF rReset.Q AND S_EStop AND NOT ((B_Clamped AND B_Unclamped) OR (B_PressUp AND B_PressDown)) THEN
        faultCode := 0; state := HOMING;
      END_IF;
    ESTOP:                                (* 急停松开后也不自己动，按复位才回原点 *)
      IF S_EStop AND rReset.Q THEN state := HOMING; END_IF;
  END_CASE;

  (* 4. 输出 *)
  jog := NOT auto AND (state = IDLE OR state = INIT OR state = FAULT);   (* 故障时允许点动，联锁照样有效 *)
  Y_Clamp     := state = CLAMPING OR state = PRESSING OR state = RETURNING OR (jog AND S_JogClamp)
                 OR ((state = FAULT OR state = ESTOP) AND clampHold);
  Y_PressDown := ((state = PRESSING AND S_Hand1 AND S_Hand2) OR (jog AND S_JogDown AND B_Clamped)) AND S_LC AND S_EStop;
  Y_PressUp   := (state = RETURNING OR (state = HOMING AND NOT B_PressUp) OR (jog AND S_JogUp))
                 AND S_EStop AND NOT Y_PressDown;
  H_OK    := resOk;
  H_NOK   := resNok;
  H_Ready := state = IDLE;
  H_Fault := state = FAULT OR state = ESTOP;
END_PROGRAM
