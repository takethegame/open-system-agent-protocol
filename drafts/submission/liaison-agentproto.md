# 联络信草稿 — agentproto WG

> 用法:填入真实署名后由实际提交人发送给 `agentproto` WG chairs。**这是草稿,不会自动发出。** 收件人以 wgchairs 页为准。

---

主题:Review request — two individual drafts on local agent capability tokens and consent receipts

Dear agentproto chairs,

I am one of the authors of two individual submissions that may be relevant
to this working group's scope. Both documents are complete, compile with
xml2rfc v3, and are backed by a reference implementation (Apache-2.0), an
executable conformance suite (68 cases across eight levels, currently 64
automated passes), formal TLA+ models, and a security-oriented hardening
log. I am not asking the group to adopt them — I am asking whether the
topic and the framing belong here, and whether the group would be willing
to review them.

- `draft-zeng-osap-capability-tokens` defines a signed capability token for
  delegating authority between agents on a single local system: ten
  attenuation rules, stateless audience/task/subject binding, revocation
  with cascade, and consent prerequisites for high-risk actions. It does
  not define transport or discovery.
- `draft-zeng-osap-consent-receipts` defines the consent request/receipt pair
  with reservation ordering, a linkage to capability issuance, and an
  informative mapping to ISO/IEC 27560. It does not define the UI.

Positioning: OSAP is deliberately a **local binding and federation layer**
next to, not instead of, existing work — MCP/A2A for agent surfaces, OAuth
and WIMSE for tokens and security, SPIFFE for identity. The drafts are
narrow on purpose: token format and consent artifacts only. The full
system context (bus, discovery, task state machine) is in the reference
implementation, not in the drafts.

Questions for the chairs:

1. Is this within the group's charter, or does it belong to another
   working group (we are also contacting OAuth given the receipt format)?
2. If in scope, would the chairs welcome an individual submission for
   review, or prefer to wait for broader input first?

Both drafts and the implementation are public; I can share links in a
follow-up once the submission prerequisites (contributor consent and IPR
disclosure, per BCP 78/79) are complete.

Thanks,

Zeng Zhiyong
272577337@qq.com
