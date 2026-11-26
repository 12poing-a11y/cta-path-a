# -*- coding: utf-8 -*-
"""Register the Windows scheduled tasks (design §2 + decision 1/4): run 17:30, retries 18:30 / 20:00 / 22:00, judge + backfill 08:30.
Weekdays only. WakeToRun and StartWhenAvailable are set so a sleeping machine wakes and a missed run starts at the next chance."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from . import config as C

TASKS = {
    "CTA_Official_Run_1730": ("17:30", "run"),
    "CTA_Official_Retry_1830": ("18:30", "run"),
    "CTA_Official_Retry_2000": ("20:00", "run"),
    "CTA_Official_Retry_2200": ("22:00", "run"),
    "CTA_Official_Judge_0830": ("08:30", "judge"),
}

XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>CTA official daily data pipeline ({desc})</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-11-30T{time}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><Monday /><Tuesday /><Wednesday /><Thursday /><Friday /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <WakeToRun>true</WakeToRun>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python}</Command>
      <Arguments>-m official_pipeline {cmd}</Arguments>
      <WorkingDirectory>{cwd}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def task_xml(time: str, cmd: str) -> str:
    return XML.format(desc=f"{cmd} {time}", time=time, python=sys.executable, cmd=cmd, cwd=str(C.ROOT))


def install(log=print) -> None:
    tmp = Path(tempfile.mkdtemp())
    for name, (time, cmd) in TASKS.items():
        xml = tmp / f"{name}.xml"
        xml.write_text(task_xml(time, cmd), encoding="utf-16")
        r = subprocess.run(["schtasks", "/Create", "/TN", name, "/XML", str(xml), "/F"], capture_output=True, text=True)
        log(f"schtasks {name} {time} {cmd}: rc={r.returncode} {r.stdout.strip()} {r.stderr.strip()}")
