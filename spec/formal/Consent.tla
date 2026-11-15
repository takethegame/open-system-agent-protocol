---- MODULE Consent ----
\* Consent request ordering (standard.md §10.2, §10.3).
\*
\* A request moves through none -> requested -> reserved -> granted -> activated,
\* or stops at denied. Revocation is only possible after activation and is
\* terminal. A cap_id is reserved before the user decision and becomes active
\* only when the granted receipt is activated.

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Requests, Caps

Phases == {"none", "requested", "reserved", "granted", "denied",
           "activated", "revoked"}

VARIABLES phase, reserved, active, granted_once

vars == <<phase, reserved, active, granted_once>>

Init ==
  /\ phase = [r \in Requests |-> "none"]
  /\ reserved = [r \in Requests |-> 0]
  /\ active = {}
  /\ granted_once = {}

Request(r) ==
  /\ r \in Requests
  /\ phase[r] = "none"
  /\ phase' = [phase EXCEPT ![r] = "requested"]
  /\ reserved' = reserved
  /\ active' = active
  /\ granted_once' = granted_once

Reserve(r, c) ==
  /\ r \in Requests
  /\ c \in Caps
  /\ phase[r] = "requested"
  /\ \A other \in Requests : reserved[other] /= c
  /\ phase' = [phase EXCEPT ![r] = "reserved"]
  /\ reserved' = [reserved EXCEPT ![r] = c]
  /\ active' = active
  /\ granted_once' = granted_once

Grant(r) ==
  /\ r \in Requests
  /\ phase[r] = "reserved"
  /\ phase' = [phase EXCEPT ![r] = "granted"]
  /\ reserved' = reserved
  /\ active' = active
  /\ granted_once' = granted_once \cup {r}

Deny(r) ==
  /\ r \in Requests
  /\ phase[r] \in {"requested", "reserved"}
  /\ phase' = [phase EXCEPT ![r] = "denied"]
  /\ reserved' = reserved
  /\ active' = active
  /\ granted_once' = granted_once

Activate(r) ==
  /\ r \in Requests
  /\ phase[r] = "granted"
  /\ phase' = [phase EXCEPT ![r] = "activated"]
  /\ reserved' = reserved
  /\ active' = active \cup {reserved[r]}
  /\ granted_once' = granted_once

Revoke(r) ==
  /\ r \in Requests
  /\ phase[r] = "activated"
  /\ phase' = [phase EXCEPT ![r] = "revoked"]
  /\ reserved' = reserved
  /\ active' = active \ {reserved[r]}
  /\ granted_once' = granted_once

Next ==
  \/ \E r \in Requests : Request(r)
  \/ \E r \in Requests : \E c \in Caps : Reserve(r, c)
  \/ \E r \in Requests : Grant(r)
  \/ \E r \in Requests : Deny(r)
  \/ \E r \in Requests : Activate(r)
  \/ \E r \in Requests : Revoke(r)

Spec == Init /\ [][Next]_vars

TypeOK ==
  /\ phase \in [Requests -> Phases]
  /\ reserved \in [Requests -> Caps \cup {0}]
  /\ active \subseteq Caps
  /\ granted_once \subseteq Requests

\* A receipt can only exist after a cap_id reservation.
GrantHasReservation ==
  \A r \in Requests :
    phase[r] \in {"granted", "activated", "revoked"} =>
      reserved[r] /= 0

\* At most one request can reserve a given cap_id.
UniqueReservation ==
  \A r1, r2 \in Requests :
    (reserved[r1] = reserved[r2] /\ reserved[r1] /= 0) => r1 = r2

\* Active caps are exactly the caps of activated requests.
ActiveMatchesPhase ==
  \A c \in Caps :
    c \in active <=>
      \E r \in Requests :
        phase[r] = "activated" /\ reserved[r] = c

\* Denial is terminal: a denied request never exposes an active cap.
DeniedIsInactive ==
  \A r \in Requests :
    phase[r] = "denied" => reserved[r] \notin active

\* Revocation is terminal and removes the activated cap.
RevokedIsInactive ==
  \A r \in Requests :
    phase[r] = "revoked" => reserved[r] \notin active

\* Activation is reachable only after the user granted this request.
ActivationHadGrant ==
  \A r \in Requests :
    phase[r] \in {"activated", "revoked"} => r \in granted_once

====
