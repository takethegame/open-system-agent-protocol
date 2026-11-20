# 联络信草稿 — OAuth WG

> 用法:填入真实署名后由实际提交人发送给 OAuth WG chairs(收件人以 wgchairs 页为准)。同意回执与 OAuth 的 token/consent 接口有交集,故单独联络。**这是草稿,不会自动发出。**

---

主题:Review request — consent receipts for local agent delegation (individual drafts)

Dear OAuth WG chairs,

I am one of the authors of two individual submissions about local agent
authorization. The one closest to this group's scope is
`draft-zeng-osap-consent-receipts`: a consent request/receipt pair for
user-delegated authority between agents running on a single system, with

- a reservation ordering that keeps capability issuance strictly behind the
  user's decision (`cap_id` reserved before grant, inert until activation),
- expiry clamping (a receipt never outlives the request),
- an Ed25519-signed receipt body with offline verification, a key
  registry keyed by `kid` with rotation/revocation semantics, and
- an informative mapping to ISO/IEC 27560.

The token side (`draft-zeng-osap-capability-tokens`, attenuation-only signed
capabilities) is deliberately separate, so each document can be reviewed on
its own. Both are backed by an Apache-2.0 reference implementation and an
executable conformance suite; the drafts contain no transport and no UI.

We are contacting agentproto as well, since the primary audience may be
agent infrastructure rather than web authorization. What we would value
most from this group is a review of the receipt data shape and the
reservation ordering against the consent patterns this group has already
standardized (and anything in flight), and an explicit statement if this
belongs elsewhere.

Questions for the chairs:

1. Does the receipt/request artifact fall within the group's current
   scope, or does it need a separate effort?
2. Would the group accept the drafts for review once the submission
   prerequisites (contributor consent, IPR disclosure per BCP 78/79) are
   complete?

Thanks,

Zeng Zhiyong
272577337@qq.com
