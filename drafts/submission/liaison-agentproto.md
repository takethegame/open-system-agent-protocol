# 联络信草稿 — agentproto WG

> 用法:由实际提交人发送给 `agentproto` WG chairs(收件人以 wgchairs 页为准)。**这是草稿,不会自动发出。** 注:agentproto 已于 2026-10 获 IESG 批准章程,IETF 127 有正式会,组内已有委派/授权类 draft——本信按此现实撰写。

---

主题:Review request — two individual drafts on local agent capability tokens and consent receipts

Dear agentproto chairs,

I am the author of two individual submissions that are adjacent to this
group's chartered work on agent communication and delegation. Both
documents are complete, compile with xml2rfc v3, and are backed by a
reference implementation (Apache-2.0), an executable conformance suite
(68 cases across eight levels, currently 64 automated passes), formal
TLA+ models, and a security-oriented hardening log. I am not asking the
group to adopt them — I am asking whether they fit the charter's scope,
and whether the group would be willing to review them relative to the
in-flight work I list below.

- `draft-zeng-osap-capability-tokens` defines a signed capability token
  for delegating authority between agents on a single local system: ten
  attenuation rules (authority monotonically non-increasing along the
  chain), stateless audience/task/subject binding enforced at the bus,
  revocation with cascade, and consent prerequisites for high-risk
  actions. It does not define transport or discovery.
- `draft-zeng-osap-consent-receipts` defines the consent request/receipt
  pair with reservation ordering (a `cap_id` is reserved before the
  user's decision and stays inert until activation), expiry clamping, an
  Ed25519-signed receipt body with offline verification and a `kid` key
  registry, and an informative mapping to ISO/IEC 27560. It does not
  define the UI.

Positioning relative to work I know of in the group: OSAP is a **local
binding and federation layer** — single device, OS sandbox semantics,
references over payloads — rather than a cross-network delegation
protocol. Compared with PACE authorization and the authority-transition
receipts drafts, the distinguishing part is not the delegation primitive
itself (we cite the Macaroons attenuation tradition) but the binding of
capabilities and consent to a local task tree, the OS-level peer
authentication, and the fail-closed restart recovery. I have also read
the WIMSE `sadp-delegation` proposal; our mechanisms differ (Ed25519
signed tokens with structured constraints versus encrypted capsules with
HMAC caveats), and I would value the group's view on whether the local
profile belongs here or as a companion profile.

Questions for the chairs:

1. Does the local, single-device profile fall within the charter's
   scope, or should it be pursued as an individual RFC-track document?
2. If in scope, would the chairs welcome the two drafts for review, in
   particular how the consent reservation ordering compares with PACE?

Both drafts and the implementation are public; I can share links in a
follow-up. Per BCP 78/79, the submission prerequisites (contributor
consent and an IPR self-check) are being completed by the author as the
sole contributor.

Thanks,

Zeng Zhiyong
272577337@qq.com
