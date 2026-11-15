---- MODULE Recovery ----
\* Crash reconciliation with the three §8.11 states: intent, outcome, unknown.
\*
\* A side effect moves idle -> intent -> executed -> done. A crash may happen
\* after the intent or after the effect, leaving `unknown`; reconciliation then
\* queries the effect store. If nothing ran, the task returns to idle; if the
\* effect ran, it records the outcome. Blind retry from `unknown` is a negative
\* control: when enabled, the effect can run twice and TLC must find it.

EXTENDS Naturals, TLC

CONSTANTS MaxExec, AllowBlindRetry

VARIABLES phase, executions

vars == <<phase, executions>>

Init ==
  /\ phase = "idle"
  /\ executions = 0

Begin ==
  /\ phase = "idle"
  /\ phase' = "intent"
  /\ executions' = executions

Execute ==
  /\ phase = "intent"
  /\ phase' = "executed"
  /\ executions' = executions + 1

RecordOutcome ==
  /\ phase = "executed"
  /\ phase' = "done"
  /\ executions' = executions

Crash ==
  /\ phase \in {"intent", "executed"}
  /\ phase' = "unknown"
  /\ executions' = executions

ConfirmNotExecuted ==
  /\ phase = "unknown"
  /\ executions = 0
  /\ phase' = "idle"
  /\ executions' = executions

ConfirmExecuted ==
  /\ phase = "unknown"
  /\ executions = 1
  /\ phase' = "done"
  /\ executions' = executions

BlindRetry ==
  /\ AllowBlindRetry
  /\ phase = "unknown"
  /\ phase' = "intent"
  /\ executions' = executions

Next ==
  \/ Begin \/ Execute \/ RecordOutcome \/ Crash
  \/ ConfirmNotExecuted \/ ConfirmExecuted \/ BlindRetry

Spec == Init /\ [][Next]_vars

TypeOK ==
  /\ phase \in {"idle", "intent", "executed", "done", "unknown"}
  /\ executions \in 0..MaxExec

\* §8.11: a crash before the outcome must not cause the side effect to run
\* twice. Only a confirmed reconciliation may leave `unknown`.
AtMostOnce ==
  executions <= 1

\* An effect is only recorded after an intent.
IntentBeforeExecute ==
  executions > 0 => phase \in {"executed", "done", "unknown"}

\* `done` means exactly one confirmed outcome.
DoneHasOutcome ==
  phase = "done" => executions = 1

====
