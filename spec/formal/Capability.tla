---- MODULE Capability ----
\* Capability attenuation and revocation invariants (standard.md §5.3, §5.5).
\*
\* Caps is the finite set of capability identifiers; 1 is pre-issued as a root.
\* A capability is either a root (parent = 0) or a child of an issued token.
\* Revoke marks the target and every reachable descendant in one atomic step,
\* which is the observable behavior the reference implementation promises.

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Caps, Actions, Resources, MaxExp, MaxDepth, AllowWidening

Capability ==
  [id : Caps,
   parent : Caps \cup {0},
   depth : 0..MaxDepth,
   actions : SUBSET Actions,
   resources : SUBSET Resources,
   exp : 0..MaxExp]

VARIABLES issued, revoked

vars == <<issued, revoked>>

Init ==
  /\ issued =
       {[id |-> 1,
         parent |-> 0,
         depth |-> 0,
         actions |-> Actions,
         resources |-> Resources,
         exp |-> MaxExp]}
  /\ revoked = {}

IssuedIDs == {c.id : c \in issued}

Issue ==
  \E c \in Capability :
    /\ c.id \notin IssuedIDs
    /\ c.parent = 0
    /\ c.depth = 0
    /\ c.actions = Actions
    /\ c.resources = Resources
    /\ c.exp = MaxExp
    /\ issued' = issued \cup {c}
    /\ revoked' = revoked

Attenuate ==
  \E parent \in issued :
    \E child \in Capability :
      /\ parent.id \notin revoked
      /\ child.id \notin IssuedIDs
      /\ child.parent = parent.id
      /\ child.depth = parent.depth + 1
      /\ (AllowWidening \/ child.actions \subseteq parent.actions)
      /\ (AllowWidening \/ child.resources \subseteq parent.resources)
      /\ (AllowWidening \/ child.exp <= parent.exp)
      /\ issued' = issued \cup {child}
      /\ revoked' = revoked

\* Bounded transitive closure over the current issued tree.
RECURSIVE DescendantsWithin(_, _)
DescendantsWithin(depth, S) ==
  IF depth = 0
  THEN S
  ELSE
    DescendantsWithin(
      depth - 1,
      S \cup {c.id : c \in {x \in issued : x.parent \in S}})

Revoke ==
  \E target \in IssuedIDs :
    /\ revoked' = revoked \cup DescendantsWithin(MaxDepth, {target})
    /\ issued' = issued

Next == Issue \/ Attenuate \/ Revoke

Spec == Init /\ [][Next]_vars

TypeOK ==
  /\ issued \subseteq Capability
  /\ revoked \subseteq Caps

\* §5.3: a child never widens actions, resources, or expiry, and its depth is
\* exactly one more than its parent.
AttenuationMonotonic ==
  \A c \in issued :
    c.parent /= 0 =>
      \E p \in issued :
        /\ p.id = c.parent
        /\ c.actions \subseteq p.actions
        /\ c.resources \subseteq p.resources
        /\ c.exp <= p.exp
        /\ c.depth = p.depth + 1

\* §5.5: revoking a token revokes every direct child; by induction over the
\* finite tree this covers every descendant at any depth.
RevocationCascade ==
  \A c \in issued :
    c.id \in revoked =>
      \A d \in issued :
        d.parent = c.id => d.id \in revoked

====
