(* 数字工厂分拣线 SORT-01 的参考程序：先进先出跟踪分拣（金属 → 1 号箱，红 → 2 号箱，蓝 → 3 号箱，高件 → 末端废品），
   推杆伸出 0.3 s 不到位即报故障（faultCode = 推杆号）：输送带停、故障灯亮；按停止再按启动恢复，带上剩下的件放行到末端。 *)
PROGRAM Main
  VAR
    kind : ARRAY[0..31] OF INT;          (* 1 金属 2 红 3 蓝 9 废品（高件） *)
    gone : ARRAY[0..31] OF BOOL;
    nIn, s1, s2, s3 : INT;               (* 进检测工位的件数；各推杆已处理到第几件 *)
    rIn, r1, r2, r3, rStart : R_TRIG;
    push1, push2, push3 : TP;
    t1, t2, t3 : TON;                    (* 推杆伸出监视 *)
    run, fault : BOOL;
    faultCode : INT;
    k : INT;
  END_VAR

  (* 启停与故障复位：停止（常闭）断开即复位故障；启动的上升沿重新开始，带上的件不再跟踪 *)
  rStart(CLK := S_Start);
  IF NOT S_Stop THEN fault := FALSE; faultCode := 0; END_IF;
  IF rStart.Q AND S_Stop AND NOT fault THEN run := TRUE; s1 := nIn; s2 := nIn; s3 := nIn; END_IF;
  IF NOT S_Stop OR fault THEN run := FALSE; END_IF;

  (* 检测工位：记下这一件该去哪里 *)
  rIn(CLK := B_Insp);
  IF rIn.Q AND run THEN
    IF B_Tall THEN k := 9; ELSIF B_Metal THEN k := 1; ELSIF B_Red THEN k := 2; ELSE k := 3; END_IF;
    kind[nIn MOD 32] := k; gone[nIn MOD 32] := FALSE; nIn := nIn + 1;
  END_IF;

  (* 三个推杆：件到了推杆前，按队列里的记录决定推不推 *)
  r1(CLK := B_P1);
  IF r1.Q AND s1 < nIn THEN
    IF kind[s1 MOD 32] = 1 THEN gone[s1 MOD 32] := TRUE; push1(IN := TRUE, PT := T#400ms); END_IF;
    s1 := s1 + 1;
  END_IF;
  r2(CLK := B_P2);
  IF r2.Q THEN
    WHILE s2 < nIn AND gone[s2 MOD 32] AND s2 < s1 DO s2 := s2 + 1; END_WHILE;
    IF s2 < nIn THEN IF kind[s2 MOD 32] = 2 THEN gone[s2 MOD 32] := TRUE; push2(IN := TRUE, PT := T#400ms); END_IF; s2 := s2 + 1; END_IF;
  END_IF;
  r3(CLK := B_P3);
  IF r3.Q THEN
    WHILE s3 < nIn AND gone[s3 MOD 32] AND s3 < s2 DO s3 := s3 + 1; END_WHILE;
    IF s3 < nIn THEN IF kind[s3 MOD 32] = 3 THEN gone[s3 MOD 32] := TRUE; push3(IN := TRUE, PT := T#400ms); END_IF; s3 := s3 + 1; END_IF;
  END_IF;
  push1(IN := FALSE); push2(IN := FALSE); push3(IN := FALSE);

  (* 推杆监视：电磁阀得电 0.3 s 还没伸出到位，就是推杆卡住或到位开关坏了 *)
  t1(IN := push1.Q AND NOT B_Y1Out, PT := T#300ms);
  t2(IN := push2.Q AND NOT B_Y2Out, PT := T#300ms);
  t3(IN := push3.Q AND NOT B_Y3Out, PT := T#300ms);
  IF NOT fault THEN
    IF t1.Q THEN fault := TRUE; faultCode := 1;
    ELSIF t2.Q THEN fault := TRUE; faultCode := 2;
    ELSIF t3.Q THEN fault := TRUE; faultCode := 3; END_IF;
  END_IF;

  M_Belt := run AND NOT fault;
  Y1 := push1.Q AND NOT fault;
  Y2 := push2.Q AND NOT fault;
  Y3 := push3.Q AND NOT fault;
  H_Run := run;
  H_Fault := fault;
END_PROGRAM
