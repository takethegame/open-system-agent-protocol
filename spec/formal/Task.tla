---- MODULE Task ----
\* Task budget and cancellation invariants (standard.md §8.6, §8.7).
\*
\* A task has a fixed budget and a consumed counter. Delegate only creates a
\* child whose budget is no larger than the parent's remaining budget. Cancel
\* marks the target plus every reachable non-detached descendant in one atomic
\* step and clears any accumulated results, so a cancelled task cannot expose
\* a result as usable. Detached children (and their subtrees) are not cancelled.

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Tasks, MaxBudget, MaxResults, MaxDepth

Task ==
  [id : Tasks,
   parent : Tasks \cup {0},
   detached : BOOLEAN,
   status : {"active", "cancelled"},
   budget : 0..MaxBudget,
   consumed : 0..MaxBudget,
   results : 0..MaxResults]

VARIABLES tasks

vars == <<tasks>>

Init ==
  tasks =
    {[id |-> 1,
      parent |-> 0,
      detached |-> FALSE,
      status |-> "active",
      budget |-> MaxBudget,
      consumed |-> 0,
      results |-> 0]}

TaskIDs == {t.id : t \in tasks}

Delegate ==
  \E parent \in tasks :
    \E child \in Task :
      /\ parent.status = "active"
      /\ child.id \notin TaskIDs
      /\ child.parent = parent.id
      /\ child.detached = FALSE
      /\ child.status = "active"
      /\ child.consumed = 0
      /\ child.results = 0
      /\ child.budget <= parent.budget - parent.consumed
      /\ tasks' = tasks \cup {child}

Consume ==
  \E t \in tasks :
    /\ t.status = "active"
    /\ t.consumed < t.budget
    /\ tasks' = (tasks \ {t}) \cup {[t EXCEPT !.consumed = @ + 1]}

Complete ==
  \E t \in tasks :
    /\ t.status = "active"
    /\ t.results < MaxResults
    /\ tasks' = (tasks \ {t}) \cup {[t EXCEPT !.results = @ + 1]}

\* Bounded closure over non-detached parent -> child edges.
RECURSIVE CancelledSet(_, _)
CancelledSet(depth, S) ==
  IF depth = 0
  THEN S
  ELSE
    CancelledSet(
      depth - 1,
      S \cup {c.id : c \in
        {x \in tasks : x.parent \in S /\ ~x.detached}})

Cancel ==
  \E target \in tasks :
    LET affected == CancelledSet(MaxDepth, {target.id})
    IN
      /\ target.status = "active"
      /\ tasks' =
           {t \in tasks : t.id \notin affected}
           \cup
           {[t EXCEPT !.status = "cancelled", !.results = 0] :
              t \in {x \in tasks : x.id \in affected}}

Next == Delegate \/ Consume \/ Complete \/ Cancel

Spec == Init /\ [][Next]_vars

TypeOK == tasks \subseteq Task

\* §8.6: budgets never grow along a delegation chain.
BudgetMonotonic ==
  \A c \in tasks :
    c.parent /= 0 =>
      \E p \in tasks :
        /\ p.id = c.parent
        /\ c.budget <= p.budget

\* §8.6: a task never consumes more than its own budget.
NoOverConsumption ==
  \A t \in tasks :
    t.consumed <= t.budget

\* §8.7: cancellation reaches every non-detached direct child; by induction
\* over the finite tree it reaches every attached descendant.
CancellationPropagation ==
  \A t \in tasks :
    t.status = "cancelled" =>
      \A c \in tasks :
        (c.parent = t.id /\ ~c.detached) =>
          c.status = "cancelled"

\* §8.7: a cancelled task exposes no result. Results produced before the
\* cancellation remain in the audit log but are cleared from usable state.
NoResultAfterCancel ==
  \A t \in tasks :
    t.status = "cancelled" => t.results = 0

====
