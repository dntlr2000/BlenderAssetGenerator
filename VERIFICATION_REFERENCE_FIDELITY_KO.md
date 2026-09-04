# Reference Fidelity 생성·평가·수정 루프 — 구현/실증 기록

기록일: 2026-09-05 KST. 시작 source commit:
`5e5b1726523c461248d82e9484b3e4c8dedb9393`.

## 판정

계획 A/P0의 공통 계약과 host 수정 경로, B 목재 실증, C의 Plastic/Rust/Crystal/Laser 전이 실증 및
D 최신 통합 호환성 검증을 완료했다. **전체 계획 완료가 아니다.** 다섯 reference 모두 고정된 관찰 feature에서 실제 개선을
source-bound 비인간 평가로 입증했지만 인간 수락은 0/5다. 실제 새 AQ multi-round host/Blender vertical은
fixture 범위에서 통과했다. B의 격리 external-intake normalization, exact 승인된 V0.7 derived optimization,
512px CPU portable PBR 변환과 최소 immutable static-payload GLB/fresh clean import도 완료했다. 최신 D에서
전체 host 회귀, 실제 Blender AQ gate, V0.9 package/handoff 및 과거 anchor 불변을 다시 통과했다. E clean
commit/baseline 기반 AQ canary+5자산 캠페인과 F delivery/Activation 재평가는 남아
있다. GLB clean import의 별도 beauty는 생성하지 않았으므로 package 외관을 인간이 수락했거나 destination
shader parity가 입증됐다는 뜻은 아니다.

기술적 terminal, 실제 시각 개선, 인간 quality disposition은 아래와 같이 별도 성과다.

| 범위 | 기술 증거 | 시각 증거 | 인간 판정 |
|---|---|---|---|
| 과거 fix3 5자산 | 기존 5/5 production/package terminal 보존 | 원래 결과의 한계 보존; 새 visual 5/5 아님 | 새 beauty 0/5, 변경 없음 |
| 새 격리 목재 | 8개 성공 build+7-pass preview, 2개 보존된 technical preview 실패, 2개 Blender 전 준비 실패, external-intake normalization/V0.7 optimization/material conversion/static-payload package/fresh clean import 통과 | attempt09에서 고정 관찰 4/4, attempt08 대비 `improved`; atlas 채널과 GLB texture binding은 확인했으나 별도 post-import beauty는 없음 | not_recorded |
| 새 격리 Plastic | 6개 build+7-pass preview, 구조 3회/국소 2회 예산 종료 | 최종 고정 관찰 4/4, 구조 초안 및 material01 대비 `improved`; abrasion 위치와 UV는 개발용 단일-view 근사 | not_recorded |
| 새 격리 Rust | fresh 구조/재질 preview와 historical paired preview, 누락 dependency로 인한 기술 실패 1회 및 동일 source 교정 retry 1회 | paired baseline의 4개 defect를 모두 해소해 `improved`; direct score는 `.969142→.612656` | not_recorded |
| 새 격리 Crystal | fresh 구조 preview 2회와 historical paired preview | 초안의 floating-frame defect를 실제 V0.4 재진입으로 해소, paired baseline의 5개 defect 해소; direct `.919345→.447594` | not_recorded |
| 새 격리 Laser | fresh 구조 preview 2회와 historical paired preview | floating sight/돌출 module을 재진입으로 수정, paired baseline의 5개 defect 해소; direct `.987376→.526329` | not_recorded |
| 새 AQ 수정 루프 | schema/host/비용/재개/legacy 회귀와 실제 Blender multi-round vertical | 고정 fixture의 `defect→structural reentry→satisfied` 배선만 입증; 실제 자산 품질 판정 아님 | 없음 |
| raw GLB diagnostic | export 및 clean process import/inspection 실행 | 부피 유지 관찰, procedural 재질 손실 | package acceptance 아님 |

## 구현

- `reference_fidelity/`: 독립 관찰과 모델링 가설, 구조 저작 입력 검사, 실제 일곱-pass/source snapshot,
  nonhuman finding, defect별 route, 고정 조건 비교, 제한된 개발 preview.
- `autonomy_v2/quality_revision_*`: 초기 opt-in, 비terminal attempt, source-bound reentry 계획,
  root/companion 교차 예산, 회차별 receipt 선택, crash/resume 원장, 누락 관찰 보충.
- geometry promotion의 initial 집계를 재사용하지 않는 structural/parametric wrapper와 material-only
  geometry receipt carry-forward. 기존 atomic promotion/rollback과 exact host-issued policy를 재사용한다.
- supervisor/One-Prompt/skill adapter의 새 companion dispatch. legacy nonpass terminal은 유지한다.
- 구조 재진입에서 policy before/after가 가변 canonical alias를 가리키지 않도록 불변 snapshot을 결속하고,
  과거 decision은 이력으로 재검증하되 선택된 최신 action만 current canonical을 요구한다. 이는 정책을
  완화한 것이 아니라 multi-round에서 과거 증거와 현재 alias의 의미를 분리한 것이다.
- 20개 additive schema와 10개 CLI/MCP surface, project allowlist/skill registry/관련 스킬 동기화.
- 개발 preview의 전역 6회 상한은 유지하고, exact job/source/run에만 적용되는 append-only `+2`
  계약과 성공/기술 실패 outcome 원장을 추가했다. 두 번째 확장 슬롯은 동일 입력 기술 실패에만 열린다.
- 첫 확장의 primary가 정상 완료돼 그 retry가 닫힌 뒤에도 새 전략을 job 변경으로 초기화하지 않도록
  additive extension `0.2.0`을 추가했다. 이전 extension/outcome, 변경된 SceneSpec, nested mesh/texture
  dependency closure와 build fingerprint를 exact scope로 계획하며, 그 SHA의 사용자 승인이 없으면 발행하지
  않는다. 닫힌 이전 retry를 되살리지 않고 새 primary 1회와 pre-beauty 동일 입력 technical retry 1회만 연다.
- 기록된 `procedural_wood_v1` channel SHA를 회귀 fixture로 고정하고 additive `procedural_wood_v2`를
  추가했다. 새 방향성 preflight는 typed `DirectionalMappingEvidenceV01`을 다시 읽어 exact texture/UV
  binding, fibre axis, 단일 harmonic 지배와 실제 tile sampling span을 Blender 전에 검사한다. 호출자가
  domain/span 숫자만 바꾸면 exact mapping과 달라 fail-closed한다. 이는 reference similarity 또는 실제
  beauty 개선 판정이 아니다.

상세 사용법과 제한은 [reference_fidelity.md](docs/reference_fidelity.md)에 있다. 스킬 지침만 변경한 구현이
아니며 실제 host에 검증·예약·전환·receipt 선택이 들어 있다. 반대로 host 코드/fixture 통과만으로 실제
생성 품질이나 새 AQ 전체 경로가 검증됐다고 주장하지 않는다.

## A/B 목재 증거

원본은 `workspaces/aq_first_completion_n03_fix3_03_weathered_wood_beam/`이며 수정하지 않았다.
개발 실증 root는 `.b/fid/fidelity_wood_b01/`이다. 과거 silhouette 본체는 비교용으로만 복사했고,
새 본체는 관찰한 top/side/end 관계에서 작성한 loft이다. staging script는
`.t/fidelity-implementation/wood_probe.py`; 공통 service에 자산 이름/sequence 분기는 없다.

### 동일 카메라 비교

Camera fingerprint: `ac57ed41549b8fbce9670452b8f7d3d40a0fbea950bbf203739d19e8e162df43`.
512×512, Blender 5.0.1, EEVEE. 각 회차의 실제 lighting/camera/render condition sidecar를 비교했다.
초기 camera는 가설이지 측정값이 아니다. 후보 자체 방향은 수정했지만 비교 camera는 유지했다.

| run | 결과 | V0.6 direct / IoU | 관찰 |
|---|---|---|---|
| `volume` | technical failure | QA 완료 안 됨 | scope tag 누락; 증거 보존 |
| `volume_scopefix` | preview 완료 | .761413 / .681349 | 연속 체적·실제 절단면, 균열/재질 미충족 |
| `baseline` | technical failure | QA 완료 안 됨 | 비교용 nested mesh source 누락; 증거 보존 |
| `baseline_depfix` | preview 완료 | .989347 / .99023 | 과거 판상 본체+rails; 높은 direct와 구조 결함 공존 재현 |
| `split` | preview 완료 | .843614 / .80076 | 본체에 두 길이 방향 함몰, top/side/end 연결 |
| `material` | preview 완료 | .843614 / .80076 | isotropic 반점은 늘었으나 방향성 wood grain 미충족 |
| `material_directional` | preview 완료 | .843614 / .80076 | 방향 band는 생겼지만 어둡고 매끈한 plastic처럼 보여 wood surface 미충족 |
| `material_directional_v2_attempt03` | preview 완료 | .843614 / .80076 | 방향성·end-grain은 개선됐지만 두 broad groove와 어둡고 매끈한 재질 미해결 |
| `structural_material_attempt08` | preview 완료 | .844829 / .801414 | strict manifold 불규칙 depression으로 구조 3/4 충족; 매끈하고 반복적인 풍화 재질은 major 결함 |
| `material_refinement_attempt09` | preview 완료 | .844829 / .801414 | 동일 spatial geometry에서 길이 방향 grain·end grain·거칠기/normal breakup 개선; 고정 관찰 4/4 |

`baseline_depfix`는 비교용으로 정규화한 constant-PBR 재질을 사용했다. 원래 V0.5 재질 전체의 재현이라고
주장하지 않는다. geometry/direct score 재현과 actual paired preview를 구분한다. 균열은 여전히 규칙적이고
bevel이 계단형인 스타일 한계도 있다. 구조가 개선됐다는 관찰은 photorealistic reference fidelity 수락이 아니다.

- 가설: [.b/fid/fidelity_wood_b01/fidelity/hypothesis.json](.b/fid/fidelity_wood_b01/fidelity/hypothesis.json)
- 비교 전: [baseline beauty](.b/fid/fidelity_wood_b01/qa/runs/baseline_depfix/passes/beauty.png)
  — `fa79af74df9ed5790c1eb12ab53fa2f2d59e0587cd2d49e5d5e24938f7c4c4c4`
- 비교 후: [material beauty](.b/fid/fidelity_wood_b01/qa/runs/material/passes/beauty.png)
  — `6118c1f4e149ea4a722978ca6b9e5554f6b6bb314654caf108f9e94858297dda`
- [nonhuman evaluation](.b/fid/fidelity_wood_b01/fidelity/inspection/material/evaluation.json)
  — `0b6417ae0650bfce5bd441739b699068416f79cb4b787cd8aac386f138496335`
- [paired comparison](.b/fid/fidelity_wood_b01/fidelity/comparisons/baseline_depfix--material.json)
  — `b2304363948f4efaa0d82a894500a319e1d78f15e817b06d627290c9f86944d0`
- [directional beauty](.b/fid/fidelity_wood_b01/qa/runs/material_directional/passes/beauty.png)
  — `02089b5a7634f5b8552b288c2ecb3c9f6cad56a76abb45e94640ec01e505b241`
- [directional nonhuman evaluation](.b/fid/fidelity_wood_b01/fidelity/inspection/material_directional/evaluation.json)
  — `88f3a9df90beba4dd04707703a1dc61894bbdaaba2701b2bf8e21b56eae3808c`
- [material→directional comparison](.b/fid/fidelity_wood_b01/fidelity/comparisons/material--material_directional.json)
  — `22107aec48727b8e953eb02f706ec2e92bd3abdfd4966936679ccb5d7b6c0822`

이 비교는 구조 항목 3개 해결, unresolved major `directional-wood-surface` 1개, direct delta `−.145733`,
`partially_improved`, `is_human_acceptance=false`를 기록한다. 원래 .989347보다 점수가 높아야 개선이라는
규칙은 사용하지 않는다. `split → material`은 개선으로 기록하지 않았다.
`material → material_directional`도 unresolved major가 그대로여서 `unchanged`다. 생성된 source texture에는
길이 방향 pattern이 있지만 Generated-coordinate scale과 강한 저명도/normal 응답이 실제 beauty에서 넓고
매끈한 band로 나타났다. 기술적으로 완료된 실행이므로 technical retry 슬롯은 사용하지 않는다.
이 실패를 재현한 v1 texture의 dominant cross-grain harmonic 비율은 약 `.88309`였고, sampled tile span은
약 `.1525`였다. 신규 preflight는 두 조건을 각각 `single_period_dominance`와
`insufficient_sampled_span`으로 차단한다. v2 image-only positive control은 fibre axis `y`, harmonic 비율
약 `.25235`로 local preflight를 통과했다.

실제 목재용 v2 사전 준비는 기존 candidate의 위치를 움직이지 않고 meter perimeter/length UV와 seam
duplicate만 추가한 별도 append-only 경로에서 수행했다. attempt01은 exact scale mismatch로 Blender 전에
실패했으며 파일과 failure record를 보존했다. attempt02는 물리 scale `6.556727983845519`, UV extent
`8.59855792 × 6.25`, runtime scale `.1525150963`, 실제 sampled span `.953219352`를 결속했다.
preflight는 fibre axis `y`, anisotropy `.916573644`, dominant harmonic `.250088819`, findings `[]`로 통과했다.
그러나 실제 render 예산을 쓰기 전 channel을 직접 확인했을 때 지나치게 규칙적인 세로 stripe가 남아 있어
attempt02를 build하지 않았다. 이 결과를 삭제하거나 통과로 재분류하지 않고 그대로 보존했다.

- candidate SceneSpec SHA: `6135a6be670618e3392f9a1020c8a096d5a0a4c826bde3f6a9a401ae3090ecdb`.
- mapping evidence SHA: `ee4cd331b4bad1afea5f8d92e07da5bcd13a7f28cff30b95af5971f7e13d92c4`.
- preflight SHA: `644c96803904da32729bd235196e06ed3f270c1a3f898c046b9289857884e560`.
- UV spatial audit SHA: `375af6ffe661838872ea11fd20cce10ebe8f5515355d0890844349e8d12c68f3`;
  원래 1152개 vertex 위치·face를 seam duplicate 9개를 접은 뒤 exact 비교하고 pose/camera/reference source도
  같음을 확인했다. 이는 재질의 시각 품질 판정이 아니다.

동일한 공통 `procedural_wood_v2` 저작기를 불규칙한 multi-scale warp, knot 주변 fibre 굴절, 비정수
secondary ridge와 더 유효한 height/normal/roughness 변동으로 수정했다. 이를 attempt02의 prior texture
manifest에 결속한 append-only attempt03(provider version `0.2.1`)으로 다시 생성했다. 직접 channel 검사는
straight-band/flat-channel 회귀가 해소됐음을 확인했고, preflight는 fibre axis `y`, anisotropy
`.666783474`, dominant harmonic `.260372672`, sampled span `.953219352`, findings `[]`로 통과했다.

- attempt03 candidate SceneSpec SHA: `73e1b750a1c03d7ea96decbe2928b8152446a2b79737371ccbd2a1456b31e49f`.
- attempt03 texture manifest SHA: `c9bfaa3082ddaa80a868fd73e78657d8c621a1bbd2547cdd121c8d19d3d310a5`.
- attempt03 base-color SHA: `18750c0e2a99975d9c9aab5c7cfbf5ef3d70779fd9b50aee1f541c4d2c8ba158`.
- attempt03 mapping evidence SHA: `c2b15010a1bd5e77ef7d9decb60532052d6900c5b5a0d4dc04df60f18f0829da`.
- attempt03 preflight SHA: `4c9b2deef03be4ce19aea88891ff7c2532d3f5b6ffccfaa588c33f5047ad4b60`.
- attempt03 UV spatial audit SHA: `15eed4e9ddd0d83d07d8c182c821a84f7c30a84e015736ada730bb75964bc1fa`;
  spatial geometry, pose, camera, reference source가 모두 보존됐고 canonical write와 인간 판정은 없었다.
- 최초 read-only proposal `46aa63b45e28f7b0436b07a71ebaa87bb10f0d760914b87f8af62b83ef2528b7`은
  승인·발행 전에 implementation drift 결속을 보강하면서 superseded됐다.
- implementation-bound proposal `e2e4f0eb1c311bd66e29c5409ca88b49d929594b83c3af0863ba31f574db0f16`도
  승인·발행 전에 exact Blender binary/version 결속을 추가하면서 superseded됐다.
- 승인되어 실행된 strategy-switch extension scope SHA:
  `b4afc73df9896148cbef62b972483e2a4844b78cc69e2366e8fe105aa46fd6af`;
  build fingerprint `3d27f2cc9a49f4a8191a08fa0e755eefda439121548fdb069d43eb611facf742`,
  implementation fingerprint `8747c47c3c889fed0c5d45e7ff2bb932542734f1f8687711b38b7d421f9d2bea`,
  Blender 5.0.1 executable SHA `f81d3bca0af0d917e03fdf09255981b2ed0750d3a2815da991ea5425a87f8f7c`와 위
  SceneSpec/texture manifest/4 channels/UV mesh를 모두 결속했다. extension `0001.json`과 primary
  `material_directional_v2_attempt03`은 retry 없이 완료됐으며 아래 실제 결과와 같은 immutable chain이다.

attempt03은 same-camera Blender beauty까지 생성했지만 source-bound nonhuman evaluation이
`needs_revision`이다. 인간 quality disposition이나 B 완료를 의미하지 않는다.

승인된 V03 scope `ec090247635b469f0fb90782c5654247c3713eeaeae1533f09a4d031aa07cf26`로
`structural_material_attempt08` primary를 실제 Blender 5.0.1에서 실행했다. retry는 사용하지 않았고
reservation `0008`은 `completed` outcome으로 닫혔다. source SceneSpec SHA
`db111ebd0a263c20ef553e39ec1012078d31ad8bf6fe8244bccc798c81a5044d`, build fingerprint
`bac98ed73ef58db8037bf454e7ec9176de2532e6650d7866cb02c643ce672313`, beauty SHA
`2f6b30e6f601649b9eaf9ea136156b26e3743fb207ed6a07a05a7636ad0f9435`가 exact render evidence에
결속됐다. canonical write는 없고 인간 판정·package·campaign·Activation 권한도 없다.

- [attempt08 beauty](.b/fid/fidelity_wood_b01/qa/runs/structural_material_attempt08/passes/beauty.png)
  — `2f6b30e6f601649b9eaf9ea136156b26e3743fb207ed6a07a05a7636ad0f9435`.
- [attempt08 nonhuman findings](.b/fid/fidelity_wood_b01/fidelity/inspection/structural_material_attempt08/visual_findings.json)
  — `0552163102f569a7471f0efb01a3809cf75159a484be3f29c45289d24b8c38f9`.
- [attempt08 evaluation](.b/fid/fidelity_wood_b01/fidelity/inspection/structural_material_attempt08/evaluation.json)
  — `4239d029b9dfd9439a8e5d167172d58d08582e77e55504fdd5d01b3631e01574`.
- [attempt03→attempt08 comparison](.b/fid/fidelity_wood_b01/fidelity/comparisons/material_directional_v2_attempt03--structural_material_attempt08.json)
  — `e8a98e2bf4b022ede9ad74111f67cd14b75847497a041d512f7dbba3a4557bbf`.

고정 관찰 4개 중 연속 체적·절단면·실제 depression 3개를 충족했고, attempt03의
`longitudinal-cracks` finding은 해소됐다. `directional-wood-surface`는 reference보다 매끈하고
저대비·반복적이며 측면의 섬유/옹이/roughness breakup이 부족해 major finding으로 남았다. 평가는
`needs_revision`, `next_action=material_revision`, paired outcome은 `partially_improved`, direct delta는
`+.001215`다. 이 작은 점수 변화 자체를 개선 근거로 사용하지 않았으며 인간 `needs_revision`도 아니다.

attempt08 조사에서 image channel의 `strength`가 현재 Blender material graph에서 소비되지 않고,
image-backed height/normal의 실제 제어는 `procedural.normal_strength`/`bump_strength`/`bump_distance`라는
계약 누락을 확인했다. loader가 이 runtime controls를 image manifest에서도 유한성·범위·intended scale로
검증하도록 보완했으며, 과거 channel `strength`를 새 의미로 소급 활성화하지 않았다.

append-only `material_directional_v2_attempt09` candidate는 attempt08과 동일한 spatial
geometry/pose/camera/reference를 유지하면서 contrast·knot·roughness와 명시적인 runtime normal/bump
controls만 바꾼다. SceneSpec SHA는
`84d8939039b61343ceca872977e5b6fa95b576bdd60d00520d3a3703e11ad350`, texture manifest SHA는
`cf5465891f233af12f1b5e686ad4790589b562b992dea8000b622a804bc269a6`, directional preflight SHA는
`242ed776f8248c7de21307b4f2eca1188d62eda15e06c8777cee645b59612a8f`, spatial audit SHA는
`2e57c589ac5ded568d7e302b82afb68f902013ec5be3fba1242803778a041496`다. 이후 exact V04 승인으로
extension/reservation을 한 번 소비해 Blender preview를 실행했지만 canonical write, 인간 판정, package 또는
Activation은 여전히 없다.

V04 material-refinement 계약은 attempt08의 exact nonhuman findings/evaluation, 이전·신규 dual spatial
audit, 동일 structural source/mesh와 새 dependency closure를 scope에 묶고, primary 1회와 beauty 전
identical-input technical retry 1회만 허용한다. 누적 cap은 14이나 닫힌 retry 세 개를 되살리지 않아 실제
최대 reservation은 11이다. primary가 정상 완료됐으므로 retry는 닫혔다.

실행에 사용한 V04 scope SHA는
`0f650030829c32f085e1a48648d1a84d4a66aae0738717d8f085e01e723d2e98`다. build fingerprint
`37cf1321e82464fe58b86a88295983953048e76fb515d585f1fa720276cb31e0`, implementation fingerprint
`68bf5e0d2e74237af4c5f23f0d1b6150381e20b8ed78ba21568c6d2f227c8177`, Blender executable SHA
`f81d3bca0af0d917e03fdf09255981b2ed0750d3a2815da991ea5425a87f8f7c`와 5.0.1을 결속한다. extension SHA는
`4bff9b6e190d8b239aa70d7ae6915eaf207ade89693c987e8c6d07b1e782e6fe`, reservation SHA는
`6c8d3364ccd79de4345100417107a2bfcc31ecd5b48180165bac36cfdcbf9172`, completed outcome SHA는
`efd6bb5f07621a141f56b87abfd84287b4e14e1ae3a5de3bf1eec0ecea948507`다. result SHA는
`ba45de71e82704cd4f5173bb2b3197c729a3d5f18f9eae1057ae0b1cd90da5ba`, beauty SHA는
`e03dbf968acc61e279ad39dd94714ff204ae5f325951a477aa620cbfb9d29297`다.

source-bound visual findings SHA `c9db0179bf58ecdb66f68c07ddfa857c1cf3cc23b5fd6ffea473477e6f539ec3`와
evaluation SHA `91728ddafe19b530ad74a71893fcd294116c1ce70b522593ace4558d1a64a2ba`는 4/4
`visually_satisfied`를 기록한다. attempt08→09 comparison SHA
`41a24ddf2c27e7261c439832889f00f9970cdcf1664fd34dcdd36e2a4b73ad46`는 direct delta 0에서도 실제
미해결 feature 해소를 근거로 `improved`이며, human acceptance가 아니다.

별도 fixed UV-sphere fixture에서는 `procedural_wood_v2`가 실제 Blender 5.0.1에서 compile, save, reopen,
256×256 EEVEE neutral preview까지 통과했다. smoke receipt SHA는
`e979c510e19363517832d9b7bfb17cf2b1fd1572801fd3e6c87e3d9da664afd4`, preview SHA는
`c3baaa9daf0764aba1f19d0ef1758c4da876aa2efa5bed3262ea9b1398e8234d`다. 이 fixture는 현재 목재
geometry의 beauty도, reference similarity도 검증하지 않는다.

### 최소 GLB 진단

별도 예약한 source inspection/export/clean import inspection 3개 process를 실행했다. 새 geometry build나
QA 회차, V0.7 package acceptance 또는 destination write는 아니다.

- GLB SHA: `c3e54a6cff3a7616ded33c8164dbc80f246c7e59efaeb7261085d3737b55a9b3`.
- [source/import/result](.b/fid/fidelity_wood_b01/fidelity/glb_diagnostic/result.json).
- source/import에 본체 1개가 있고 world bbox 최대 관찰 차이는 약 `1e-6 m`였다. 이는 전체 corner
  geometry-survival gate나 V0.7 round-trip receipt가 아니다.
- raw export는 Noise/ramp/Bump 그래프와 custom properties를 보존하지 못했다. 재수입 material은
  흰 base color/roughness 1, UV0 없음이다. **portable material fidelity 미완료**다.
- 기존 V0.7의 파생 UV/bake/portable conversion 및 공식 clean-import 경로를 사용해야 한다. 이 실패를
  shader 지원 확장이나 임의 Blender Python으로 숨기지 않는다.

### 격리 external-intake 및 V0.7 준비

attempt09 source를 원본 workspace 밖의 별도 진단 job `fidelity_wood_portable_b01`에 복사해 기존
external-static-asset intake 경계를 재사용했다. 이 경로는 향후 external asset bridge의 구현이나 로드맵
선취가 아니라, B에서 기존 V0.7 portable material 경로를 실제 목재에 적용하기 위한 격리 adapter다.

- 사용자가 승인한 intake plan SHA는
  `254140fcde4731a045d129a17c27cc9df806a6811938fd7b0d86e866822a8b3b`이며 approval은 exact one-time으로
  소진됐다. source와 4개 image dependency는 계획 SHA와 모두 일치했다.
- 원본 attempt09 scene과 intake source SHA는 모두
  `57882365ba38c026f6eb6f1d3b407f69b810d86baec93504898784ad290c81d9`로 유지됐다.
- Blender 5.0.1 normalization 결과 SHA는
  `e51f25e425f7d98011ee3690d6fca5c2057ddbaf90c4fa80cdffac54be568e52`다. intake validation은 source,
  dependencies, used approval, contracts, normalized blend, embedded build와 receipt를 모두 current로 판정했다.
- `portable_gltf` 진단 profile은 LOD/collision/consolidation/UV1을 비활성화해 한 mesh·한 material의
  변환 생존만 분리해서 검사한다. V0.7 preflight는 2,082 vertices, 4,160 triangles, boundary/non-manifold/
  degenerate/negative-scale 0으로 통과했다.
- immutable optimization review plan SHA
  `0973dde804fafeb3e4b20b922c3fbaa3fc97ccfb08885ecba5326bcf6bc6dfc1`에 대한 exact 사용자 승인을 별도로
  받아 single-use로 소진했다. execution plan SHA는
  `73087207c27305c1141d11a4865850efa6e38ff7e759b1427b5eb0736992cd21`, optimized blend SHA는
  `421188756b409895627ff6b4f09b2fd51122ac77e3d6a808cef2b57724e3a095`이며 run은 `complete`다. LOD0은
  한 객체·한 재질·4,160 triangles를 유지하고, UVMap과 tangent를 보존/생성했으며 canonical source는 불변이다.
- optimized blend, execution plan, consumed approval, UV manifest, profile, external manifest, material contract와
  네 source image를 결속한 512px/16px-margin/CPU material-conversion scope SHA는
  `b080e59144ac60f8a03e9f3fec345e8103dbfe83e81a5e386c5e38340d6b8525`다. exact 승인 후 한 번 실행해
  conversion manifest SHA `bbac3ea3c38b8f4479c42022e6b8a21cd7b8275ba74bd1b54cd5d5838aa7614f`, portable Blend SHA
  `19507f209373fd88788cdcef5fcd181648f08e299fc35e1e7ec72e4a7d2ea637`를 생성했다. 결속된 23개 파일은
  재해시 결과 23/23 일치했고 원본 attempt09 SHA도 유지됐다.
- 512px atlas의 base-color/roughness/normal 채널에 실제 목재 결·거칠기·법선 변화가 존재한다. metallic과
  emission은 0 상수 채널이다. Blender 5.0.1/Cycles CPU evidence는 degenerate UV·invalid tangent·bounds
  delta를 모두 0으로 보고하지만 pixel overlap은 측정하지 않아 tile quality는 `partially_verified`다.
  procedural detail은 512px로 제한되고 height/displacement는 tangent normal로만 전달되며 opacity texture가
  없다는 손실도 유지한다. 이는 변환 성공이지 GLB material fidelity나 package acceptance가 아니다.
- `static_payload` package와 fresh post-publication clean import만 결속한 scope SHA
  `459915e9a286482a350a0bb226ff5c09f880eaa4b73aeec717f6e68b98c48268`의 exact 승인으로 package를 생성했다.
  첫 실행은 `CBM_WORKSPACE_ROOT` 미지정으로 기본 `workspaces/`를 선택해 자산을 찾기 전에 실패했고 산출물은
  없었다. 공식 workspace-root와 Blender 5.0.1을 지정한 단일 교정 실행은 성공했다.
- package manifest SHA는 `f51eed5dfbbb00e4d5e0522fcedfea88ebf54c629206a1e67826e7d406c7fddd`,
  primary GLB SHA는 `1eee51779f44059d89a6dea67b93880fd1db1aa2187a77337246ea1bc3c064e0`, fresh
  round-trip SHA는 `60580241255e2410fafbe7f1182945adeb63f25fca76fde3062216d79e6446c3`다. manifest의
  14개 파일은 크기와 SHA가 14/14 일치하고 source/normalized/optimized/converted Blend도 불변이다.
- fresh clean import는 Blender 5.0.1에서 bounds 오차 `0.0m`, semantic/material coverage `1.0`, texture-file
  binding과 active finite UV0를 확인해 `passed`다. axis/unit file metadata, split-normal/tangent exact equivalence,
  UV loop association/coordinate multiset은 독립 검증되지 않아 6개 warning으로 남는다. 별도 post-import beauty나
  package acceptance는 없으며 destination/Activation 권한도 발생하지 않는다.

## C 네 reference 전이 증거

모든 전이 job은 `.b/fid/` 아래의 격리된 새 workspace다. 과거 fix3 scene과 beauty는 비교용으로만 복사했고
새 후보의 기본 geometry로 replay하지 않았다. 각 hypothesis는 reference 관찰, 주요 부피/부품 관계와 숨은 면
불확실성을 preview 전에 고정했다. 아래 `visually_satisfied`와 `improved`는 Codex 비인간 finding을 host가
검증한 결과이며, 인간 quality disposition, package acceptance, destination write 또는 Activation이 아니다.

| 자산 | 새 구조/수정 결과 | final beauty / evaluation | paired 또는 회차 비교 |
|---|---|---|---|
| Plastic `.b/fid/fidelity_plastic_c01` | 과거 silhouette replay 없이 bowed shell, 실제 rim 두께, 부착 rib, bounded fracture를 저작하고 두 번째 local material 전략에서 sparse abrasion을 추가. 구조 `3/3`, local `2/2`, preview `6/6` 소진 | beauty `703e3c166e061c392181a226f5143886433429c2cd6fbdec4d5fb6b30bd5d983`; evaluation `48594929753aabec2422de502a73ec4c1b822b59873f64b600e7672074c6f016`, 4/4, direct `.727602` | structure02→material02 `6767020f45264b478c8d0d4df17e7249efc0a4e2b7920a1d3c83b1375e30d242`, `improved`; material01→02도 direct delta `0`에서 wear finding 해소. historical beauty `87744e870255bad71f6d4ac3c178ab662ea666e481a7bf2410ddf464b57d0834`는 직접 시각 비교만 했고 예산을 넘어 paired 재렌더하지 않음 |
| Rust `.b/fid/fidelity_rust_c02` | 세 개의 닫힌 판재 체적, rolled flange, rounded rebar, 열린 angled tube와 object-space rust breakup을 새로 저작 | beauty `75a3d1d38ac7f14991cbd5febe29e4adc2d2bb9c96623cf447d0ceb9b172b11b`; evaluation `35573ecbc08101de7c1837108e0615008d8ba056b88fba7296b0c6f38e4fda47`, 4/4, direct `.612656` | historical paired evaluation direct `.969142`, 0/4에서 comparison `1a7411525b23a278d143b5e99e7ca812e926b4a7e32373ef4df119b2d7897d61`, `improved`, 4개 해소. old beauty `641ef2268fe531131f130110ba468526bbc9556a3d74ab6ed6e3276e8f8acfcd` |
| Crystal `.b/fid/fidelity_crystal_c02` | 닫힌 ivory spine/cradle/grip, faceted chamber/muzzle/gem, 3개 swept fin과 pendant를 저작. 초안의 floating frame을 exact finding→V0.4 re-entry로 낮춘 spine/ivory grip shell+green inset으로 연결 | beauty `28c7171392c9b0c87567b804b6a6a660fe146976a6b878522023e7890259b5a1`; evaluation `7144d91883fae8d2d9e234fc1eecbdbccd33880eb61bd69b6d2100e63b664fe0`, 5/5, direct `.447594` | structure02→03 `f332b7156cc1f7e8e5fc64dbf6e7470e6eb88c54ac54ae190b2f9255d7eeb35a`, `improved`; historical paired direct `.919345`, 0/5에서 comparison `56095b45ca194db188b549590699788afef92d206475ddbce4fe58dbb8237950`, 5개 해소. old beauty `6bfbcb40b73a3aa56ca5d0af8bde3fb4c8974ffa01671f4c6ae56fe18170accb` |
| Laser `.b/fid/fidelity_laser_c01` | beveled receiver/frame/stock/grips와 기능별 재질 부품을 저작. 초안의 floating sight와 돌출 green plates를 exact finding→V0.4 re-entry로 seated sight 및 4면 bezel 뒤 module로 수정 | beauty `8c0ad41f4b587ac7ed3aed0c60c1a254263a8e8d7d7974585ca4d61f223efd4c`; evaluation `049e024c1953f9bfb3ea593a5e27b95fb030169318f8071f2f2c8e20a99285e5`, 5/5, direct `.526329` | structure02→03 `a231a0b8b5251b06808fbc37f7e4e32393477a9d9a252ff1a162369f0e23843f`, `improved`; historical paired direct `.987376`, 0/5에서 comparison `4f730842a1f69857c4af1adc4594ef15dd7de46f8477da7e41e9e1579ab3251e`, 5개 해소. old beauty `55934814b95797fce5497e2c672b052191662c79de5f378f1b341dd472291a4b` |

Rust의 첫 `c01` prepare는 관찰 bbox가 semantic evidence bbox를 벗어나 계약 단계에서 실패했고, `c02`로
새 session을 열어 수정했다. `c02` historical paired baseline 첫 실행은 nested MeshPayload closure 누락으로
beauty 전에 기술 실패했으며, 과거 dependency bytes/hash를 동일 상대 경로로 보충한 단일 retry가 성공했다.
Crystal `c01`은 SceneSpec 0.2에 없는 `emission_color` 필드를 계약이 거부해 Blender 전에 실패했고 `c02`에서
기존 `base_color + emission_strength`로 수정했다. Laser의 최초 historical review는 새 semantic target이 없는
과거 scene에 material feature를 satisfied로 표시해 host가 거부했다. 해당 review는 보존하고 별도
`laser-baseline-corrected` review에서 색 구획과 기능 부품 구조화를 구분했다.

Rust/Crystal/Laser의 historical direct score는 새 후보보다 모두 높다. 그럼에도 exact paired comparison은
각각 구조 feature 해소를 근거로 `improved`를 기록한다. 이는 기존 silhouette/bbox 중심 점수를 폐기한다는
뜻이 아니라, 높은 direct score가 올바른 부피·단면·부품 관계를 대신하지 못한다는 실제 negative control이다.
Crystal의 곡면 장식/투명 광학, Rust의 얇고 복잡한 찢김, Laser의 세부 panel seam은 여전히 단순화됐고,
Plastic abrasion 위치와 UV는 단일-view 개발 근사다. 이 한계를 숨기지 않고 E 캠페인과 인간 검토에서 별도로
평가한다.

## 호환성 및 실제 검증 기록

각 결과의 범위는 실행 시점 source다. 이후 변경은 새로운 focused/full 검증으로 갱신하며, 과거 로그는 보존한다.

| 검사 | 실행 결과/범위 |
|---|---|
| full `.t/fidelity-full-a01` | 2175 passed, 69 skipped, 8 warnings; 후속 host 보강 이전 |
| full `.t/fidelity-full-a02` | 2195 passed, 69 skipped, 8 warnings, 336.87 s; geometry payload snapshot 최종 보강 이전 |
| full `.t/fidelity-full-a03` | 2197 passed, 69 skipped, 8 warnings, 325.93 s; object-count 예산 floor/빈 필수 관찰 차단 이전 |
| full `.t/fidelity-full-a04` | **2199 passed, 69 skipped, 8 warnings, 333.18 s**; 현재 host/예산/관찰 계약 |
| full `.b/fid/pytest-full-mapping-20260904a` | 2197 passed, 13 failed, 71 skipped; 긴 basetemp로 Windows path limit이 발생한 보존된 환경 실패. 같은 15 parametrized cases는 짧은 `.b/z1`에서 통과 |
| full `.b/z2` | **2210 passed, 71 skipped, 8 warnings, 435.05 s**; typed mapping/Wood v2/최신 전체 host 회귀, 짧은 repo-local basetemp |
| full `.b/full2` | **2212 passed, 72 skipped, 9 warnings, 507.40 s**; policy snapshot/replay와 AQ vertical 등록 후 전체 회귀. 8개 기존 Pillow deprecation과 1개 보존된 pytest-cache ACL warning |
| full `.b/full-preview-switch-a01` | **2217 passed, 72 skipped, 9 warnings, 303.07 s**; strategy-switch extension 0.2.0과 최신 Wood v2 회귀를 포함한 전체 host suite |
| full `.b/full-preview-implementation-a01` | 2216 passed, 2 failed, 72 skipped; 긴 basetemp 때문에 두 AQ fixture가 Windows path limit을 넘은 보존된 환경 실패. 같은 두 테스트는 짧은 `.b/r1`에서 2/2 통과 |
| full `.b/f5` | **2218 passed, 72 skipped, 9 warnings, 314.03 s**; implementation fingerprint 보강 후 짧은 repo-local basetemp의 최신 전체 host suite |
| full `.b/f6` | **2219 passed, 72 skipped, 9 warnings, 301.03 s**; exact Blender executable/version binding까지 포함한 최신 전체 host suite |
| focused sandbox `.t/pytest-attempt08-review`, `.b/q8` | 각 실행에서 20개 완료 뒤 pytest basetemp 자체가 `WinError 5` ACL로 읽히지 않아 19 setup/cleanup error; 실패 경로를 보존하고 코드 통과로 재분류하지 않음 |
| focused `.b/q9` | **39 passed, 7.87 s**; 같은 reference-fidelity core/preview-budget/file parity 세트를 repo-local 경로와 정상 filesystem context에서 재실행 |
| focused `.t/fidelity-host-a09` | 120 passed; initial/legacy/host/skill/공개 surface |
| focused `.t/fidelity-flow-a06` | 20 passed; crash reservation adoption, cost-before-copy, retry, supplement, nested snapshots |
| actual Blender geometry smoke `.b/fidelity-geometry-smoke-a01` | 1 passed; initial geometry controller/policy/build/promotion/idempotent recovery |
| fidelity-bound Blender geometry smoke `.b/fidelity-geometry-smoke-a03` | **1 passed, 9.44 s**; exact loop/hypothesis가 실제 controller 입력과 initial geometry promotion에 도달. reentry 전체 증거는 아님 |
| AQ multi-round Blender vertical `.b/x8` | **1 passed, 68.44 s**; Blender 5.0.1 initial geometry/material/7-pass QA → source-bound finding → structural policy re-entry → 새 geometry/material/7-pass QA → 회차별 receipt/paired comparison → 필수 hard-gate `blocked` terminal. fixture의 `defect/satisfied`는 배선용 비인간 입력이며 실제 reference quality 또는 human approval이 아님 |
| AQ gate `.t/fidelity-aq-gate-a01` | focused 1109 passed/29 skipped 뒤 신규 코드의 Ruff E501로 실패; Blender 단계 미실행. 실패 로그를 통과로 재분류하지 않음 |
| AQ gate `.t/fidelity-aq-gate-a02` | **최종 exit 0**. focused 1111 passed/29 skipped/8 warnings, 180.64 s; actual Blender 52 passed/1 skipped/6 warnings, 1456.25 s; Ruff/doctor/Blender compat/benchmark/diff 통과 |
| AQ gate `.t/aqg-v2c` | **최종 exit 0**. focused 1122 passed/31 skipped/8 warnings, 204.61 s; actual Blender 54 passed/1 skipped/6 warnings, 1031.51 s; 새 Wood v2와 mapping/preflight tests 포함 |
| AQ gate `.t/aqg-fidelity-v3` | **최종 exit 0**. focused 1124 passed/32 skipped/9 warnings, 239.72 s; actual Blender 55 passed/1 skipped/7 warnings, 2061.67 s; 새 multi-round vertical, Ruff/doctor/Blender compat/benchmark/diff 통과 |
| AQ gate `.t/aqg-fidelity-v4` | **최종 exit 0**. focused 1129 passed/32 skipped/8 warnings, 159.48 s; actual Blender 55 passed/1 skipped/6 warnings, 957.79 s; strategy-switch 계약, 최신 Wood v2, Ruff/doctor/Blender compat/benchmark/diff 통과 |
| AQ benchmark 0.1 | 8/8 matched, Blender 3 cases, report SHA `0946535b3e148ddc159248ef0bc14aac2c3388fce33715dcdfe9056efa0adb39` |
| AQ benchmark 0.2 | 10/10 matched, Blender 2 cases, human `not_reviewed`, report SHA `d44f56d4d95613ab348ef23243613f322f769bf4d16feb19a91964ed2c916e56` |
| AQ benchmark 0.2 latest `.t/aqg-v2c` | 10/10 matched, Blender 2 cases, human `not_reviewed`, report SHA `a3dba658f2079c3dd0cc119f40933e024590c6758dfd4eb947970df6bd87b646` |
| AQ benchmark 0.2 latest `.t/aqg-fidelity-v3` | 10/10 matched, Blender 2 cases, human `not_reviewed`, report SHA `4158fd23f827201756857dd5286db623057c0bad000ac23e654d54866c98fccb` |
| AQ benchmark 0.2 latest `.t/aqg-fidelity-v4` | 10/10 matched, Blender 2 cases, human `not_reviewed`, report SHA `86af230621e0da91559ca97b1e719ff2779c68dfd7e6e470286158c46194b4dc` |
| V0.9 isolated gate `reports/v09_smoke/20260903T171931678Z-37416` | **최종 exit 0**. full 2199 passed/70 skipped/1 pytest-cache warning, 341.76 s; actual Blender 5.0.1 package/clean import/handoff/audit/stability PDF 통과 |
| `cbm doctor` | 실행 통과 |
| `cbm blender-compat` | Blender 5.0.1 actual GLB/FBX/OBJ smoke 통과; global derived compatibility report 생성 |
| agent instructions / incident literal / Activation contract checker | 실행 통과; Activation 실행이 아님 |
| Wood v2/preflight focused unit | **17 passed**; v1 exact channel SHA 고정, v2 determinism/axis/periodicity/span/tamper 및 mapping argument 교체 차단 |
| Wood v2 actual Blender compile fixture | **1 passed, 4.57 s**; Blender 5.0.1 compile/save/reopen/neutral preview, source manifest 불변. 목재 reference beauty 증거 아님 |
| strategy-switch preview budget focused `.b/pt-preview-switch-a04` | **8 passed**; read-only exact plan, 승인 SHA 불일치, prior completion, nested dependency/tamper, 새 primary/동일 입력 technical retry, 중복/초과 차단 |
| updated Wood v2 Blender fixture `.b/blender-wood-v2-a01` | **1 passed, 4.74 s**; attempt03 저작기 코드의 compile/save/reopen/neutral render 호환성. 목재 geometry beauty 증거 아님 |
| latest preview/material focused `.b/pt-preview-switch-a06` | **26 passed**; V02 extension/outcome, 공개 surface, Wood v1/v2 및 material authoring 회귀 |
| implementation/Blender-bound preview focused `.b/p1` | **13 passed**; runtime source/lock 및 exact Blender binary/version drift, schema/public surface 차단 포함 |
| correction extension focused `.b/p4` | **13 passed**; 완료된 과거 runtime의 가독성, V03 exact source/runtime binding, primary/technical-retry 분리 포함. 앞선 `.b/t-preview-v03`, `.t/pt3` 실행은 Windows basetemp ACL로 setup 실패했으며 통과로 세지 않음 |
| full `.b/f7` | **2222 passed, 72 skipped, 8 warnings, 332.28 s**; V03 correction extension, historical-runtime compatibility와 기존 전체 host 회귀의 현재 결과 |
| full `.b/reference-fidelity-full-final` | 2223 passed, 1 failed, 73 skipped; 긴 basetemp가 단일 AQ transition 경로에서 WinError 206을 낸 보존된 환경 실패. 해당 테스트는 짧은 `.b/f8`에서 1/1 통과 |
| full `.b/f9` | **2224 passed, 73 skipped, 8 warnings, 315.14 s**; 공통 loft cap/winding 수정과 전체 Standard/AQ host 회귀의 현재 결과 |
| AQ gate `.t/aqg-fidelity-loft-final` | **최종 exit 0**. focused 1136 passed/32 skipped/8 warnings, 169.97 s; actual Blender 56 passed/1 skipped/6 warnings, 943.74 s; Ruff/doctor/Blender compat/benchmark/diff 통과 |
| AQ benchmark 0.2 latest `.t/aqg-fidelity-loft-final` | 10/10 matched, Blender 2 cases, human `not_reviewed`, report SHA `ded41198d13158ccfb3fade403c37abcecfcd1fb541446ec80569dd7960c1915` |
| material manifest runtime controls `.b/q11` | **29 passed**; image-backed normal/bump controls의 정규화와 bool/string/NaN/out-of-range fail-closed 포함 |
| V04 material-refinement focused `.b/q14-v04` | **49 passed**; exact review/scope, dual spatial binding, primary/technical retry, schema/public surface 포함 |
| full `.b/q16` | **2236 passed, 73 skipped, 8 warnings, 439.81 s**; V04와 image-backed runtime controls를 포함한 최신 전체 Standard/AQ host 회귀 |
| AQ gate `.t/aqg-v04-material` | **최종 exit 0**. focused 1140 passed/32 skipped/8 warnings, 199.69 s; actual Blender 56 passed/1 skipped/6 warnings, 1270.57 s; Ruff/doctor/Blender compat/benchmark/diff 통과 |
| AQ benchmark 0.2 latest `.t/aqg-v04-material` | 10/10 matched, Blender 2 cases, human `not_reviewed`, report SHA `d25c7ecc46caffd162c47e6623924ce06b69f75b1e9ae2975ad649c3fd0cd40a` |
| historical preservation `.t/fidelity-implementation/preservation-a07.json` | **16/16 matched**, SHA `691ff006e6a5bdfb9edda52cf4dd04337d05a6785be231c76c17d65c2210aaf1`; normalization 뒤에도 과거 reference/beauty/Standard SceneSpec/review/terminal anchor 불변 |
| external-intake/V0.7 focused `.b/pb2` | **52 passed, 1 skipped, 2.37 s**; 샌드박스 `.b/pt-portable-b01`과 `.b/pb1`은 pytest basetemp ACL로 실패해 보존했고, 같은 세트를 정상 filesystem context에서 통과 |
| static-payload/package focused `.b/pb4` | **57 passed, 2 skipped, 2.50 s**; host packaging, V0.7 service, external intake, long-path package, material-conversion contract. 샌드박스 `.b/pb3`은 같은 basetemp ACL로 실패해 보존했고 정상 filesystem context에서 동일 세트를 통과 |
| pre-fix AQ gate `.b/aqg-0905d` | focused **1140 passed/32 skipped** 뒤 actual Blender **55 passed/1 failed/1 skipped**. 긴 controller output의 `material_plan.json`을 raw `shutil.copy2`로 promotion하며 `WinError 3`이 발생했다. 실패를 보존하고 gate 통과로 재분류하지 않음 |
| long-path promotion correction | `copy2`와 rollback staging을 기존 `native_io_path` 경계로 통일. focused `.b/pytest-mplp-0905a` **16 passed/1 skipped**, 실패했던 exact Blender vertical `.b/pytest-fidelity-vertical-0905b` **1 passed, 37.26 s** |
| final AQ gate `.b/aqg-0905e` | **최종 exit 0**. focused **1141 passed/32 skipped/8 warnings, 183.17 s**; actual Blender **56 passed/1 skipped/6 warnings, 932.58 s**; Ruff/doctor/Blender compat/benchmark/diff 통과 |
| final AQ benchmark 0.1/0.2 `.b/aqg-0905e` | 0.1 report SHA `0946535b3e148ddc159248ef0bc14aac2c3388fce33715dcdfe9056efa0adb39`; 0.2 report SHA `57959f5d5e2fbe7155136b2fb71746c7006f6c02ef7dafae5a1d7da26f0d9d71`; 실제 다섯 자산의 인간 판정이 아님 |
| final V0.9 isolated gate `reports/v09_smoke/20260904T172452884Z-16928` | **최종 exit 0**. full **2238 passed/73 skipped/8 warnings, 329.86 s**, actual external-intake **1 passed**, Blender 5.0.1 package/clean import/handoff/audit/stability PDF 통과. 중복 V0.8 gate는 생략했지만 V0.8 tests는 full suite에 포함 |
| final historical preservation `.t/reference-fidelity-history-audit-final.json` | **16/16 matched**, report SHA `691ff006e6a5bdfb9edda52cf4dd04337d05a6785be231c76c17d65c2210aaf1`; history/human disposition/Activation authority 변경 없음 |
| Activation preflight `reports/activation_readiness/validation_runs/ad4e5e8167469161-20260904t174048z` | 실제 source commit `ad4e5e816746916130e834d64a38a6b94afe6d7c`에서 full **2238 passed/73 skipped**, 필수 host/V0.7~V0.9/지침/무결성 검사는 통과했으나 actual AQ Blender가 **54 passed/2 failed/1 skipped**로 실패. 실패는 262자 converted Blend 존재 확인과 더 깊은 identity-split shadow 생성의 Windows 장경로 I/O였으며 manifest/baseline/readiness는 발행하지 않음 |
| Windows 장경로 correction focused `.b/longpath-host-0905`, `.b/activation-ad4-aq-fix1`, `.b/activation-ad4-aq-fix2` | host/계약 **126 passed/1 skipped**, Blender runner regression **4 passed**. identity-split actual Blender는 fix1에서 통과했고, converted Blend는 host 확인 뒤 Blender argv의 일반 경로 표기까지 별도로 실패한 것을 보존한 다음 native 입력 경로로 교정해 fix2 **1 passed, 79.60 s**. approval request·canonical write·package/Activation authority는 만들지 않음 |
| Activation preflight `reports/activation_readiness/validation_runs/2da54cbf676edb97-20260904t183533z` | source commit `2da54cbf676edb97bad7b323683d3ff357fda8f5`에서 앞선 **15/16** 명령은 통과했고 full **2239 passed/73 skipped/8 warnings**였으나, actual AQ Blender가 **54 passed/2 failed/1 skipped**로 실패. 장경로 존재 확인을 고친 뒤 모든 `.blend` argv에 `\\?\` 표기를 강제해 190자·135자 short path가 Blender 내부 `bpy.data.filepath`와 일반 job root 비교에서 달라진 회귀였다. 실패를 보존했고 manifest/baseline/readiness는 발행하지 않음 |
| conditional Blender input-path correction `.b/a-path-final-0447`, `.b/a-2da-fixshort-retry-0430` | 절대 경로 성질은 유지하되 260자 이상 `.blend` 입력에만 extended spelling을 사용한다. Blender runner short/long regression과 V03 reachability가 **5 passed, 29.50 s**, 실제 AQ terminal node가 **1 passed, 725.80 s**이며 상태는 `completed / quality_target_reached`. 앞선 격리 실행 `.b/a-2da-fixshort-190451`은 transition 43에서 관찰 세션이 종료돼 terminal 없이 멈췄으므로 통과로 세지 않음 |

실제 목재 strategy-switch primary `material_directional_v2_attempt03`는 승인 scope
`b4afc73df9896148cbef62b972483e2a4844b78cc69e2366e8fe105aa46fd6af` 아래 Blender 5.0.1에서 retry 없이
완료했다. extension `0001` SHA는 `4ebfe71155e216c1b5b1ea534a7d264972e77f3dad022989e0f560a42e3fbd91`,
reservation `0007`은 `859d96831af87df5d1a14543aab40577ef35e616ad7a3a101c2a0f8ced372384`, outcome `0007`은
`c039486daa54715c14662a0248fb4b50e009e2bbc9ccf5586ae3d096d41a9e85`다. beauty SHA는
`b34f33d47e0bdfb048837f1b80ba8f4a7057d2b358cf0227dbb69ca2b33e21df`, direct score `0.843614`, silhouette
IoU `0.800760`이다. source/dependency/build binding은 그대로였고 canonical write는 없었다.

직접 image inspection의 source-bound review SHA는
`c7e8a61b7f2f46a260f452177f3d59336262b1f882b9b25c44b1c7bf16e20f85`, evaluation SHA는
`37bf168b5d9670bf867ba9ccb9e01e4738a558d5ad7e004960aa05c6f94934dc`다. longitudinal/end grain은 이전보다
분명해졌지만 홈의 구조적 규칙성과 풍화 surface 부족이 각각 major finding으로 남아 `needs_revision`,
`next_action=structural_reentry`다. comparison SHA
`b256dc054fd3bffc6c5120cc1aaccfc310c28b1acc1bf185f8ca09df86346044`의 `regressed`는 과거 review가 같은 홈
결함을 satisfied로 놓친 데서 생긴 finding-set 차이이며, 이번 재질 변경이 그 형상을 새로 악화시켰다는
주장으로 사용하지 않는다. 인간 disposition은 기록하지 않았다.

조건부 skipped는 실행 통과가 아니다. mocked renderer/promotion fixture는 실제 visual/AQ campaign 증거가 아니다.
현재 플랫폼 외 지원·runtime parity를 주장하지 않는다. 최종 검증 결과는 아래 후속 항목에 추가한다.

## 과거 증거 보존

[historical anchor fixture](tests/fixtures/reference_fidelity/historical_5e5b172.json)의 16개 reference/beauty/
Standard SceneSpec/review request/campaign terminal audit SHA가 계획 당시와 일치한다.
attempt08 preview와 비인간 평가 뒤의 최종 재검사 보고서는
`.t/fidelity-implementation/preservation-a06.json`이며 16/16 일치했고 SHA-256은
`691ff006e6a5bdfb9edda52cf4dd04337d05a6785be231c76c17d65c2210aaf1`이다. 최초 `a01`은 fixture로 옮기면서 terminal
audit SHA 한 문자를 잘못 전사해 실패했고, 원래 계획의 정확한 SHA로 fixture만 수정한 뒤 `a02`로 다시
검사했다. `a01`과 원본 캠페인 파일은 보존했다. 이 검사는 지정 anchor 검사이며 전체 workspace snapshot은 아니다.

원본 review request `2f1a3b63d26a79f6d34a2fb5e165bde9d19cb17eab314b5ef5712b5b1a2cf560`은 그대로다.
과거 Standard accepted, AQ terminal/QA/approval/package 의미는 변경하지 않았다. 추가 human disposition,
package acceptance, destination write, baseline 갱신, profile Activation은 수행하지 않았다.

## 다음 진입 조건

현재 A/B/C 구현·실증과 D 통합 호환성은 완료됐다. D는 최신 full pytest, schema/repository parity,
doctor, Blender 5.0.1 compatibility, actual AQ/V0.9 gate와 과거 16개 anchor 불변으로 닫았다. 다음 순서는
아래와 같다.

1. **E clean baseline 캠페인:** D가 통과한 변경을 clean commit으로 고정하고 새 Activation source manifest,
   baseline, readiness를 만든다. 동일 baseline에서 sequence 1 canary를 먼저 실행해 정상 terminal과 source
   불변성을 확인한 뒤 sequence 2~5를 실행한다. 이번 격리 전이 결과를 새 캠페인 실적으로 재사용하지 않는다.
2. **F 분리 재평가:** 기술 terminal/clean import, 실제 시각 개선, exact 인간 quality disposition을 별도 집계한
   뒤 delivery와 Activation 가능 여부를 판단한다. 현재 5개 모두 인간 판정은 `not_recorded`다.

### B 진행 중 사용했던 조건과 해소 이력

1. 같은 목재에서 남은 structural/material correction을 입증한다. attempt03의 실제 beauty는 방향성 개선을
   보였지만 두 broad parallel grooves와 풍화 surface 부족을 닫지 못했다. isotropic noise나 장식 증량은
   대안이 아니며 먼저 좁고 불규칙한 depression과 worn section을 구조적으로 다시 저작한다.
2. append-only attempt04 candidate의 구조·재질 방향은 유지하되, 실행 전 portable topology 감사를 통해
   per-vertex UV seam의 coincident split boundary와 legacy cap의 0면적 triangle 46개를 발견했다.
   attempt04 proposal `b728e3a7826e8b9862ec86b4298ff91c9645cb77c9b3ad5cbecdf7716e0d70b6`은 승인·발행·실행 전에
   superseded했다. attempt05/06의 준비 실패는 각각 strict cap 차단과 잘못된 prior manifest 선택으로
   append-only 보존했고 Blender 실행·preview reservation·canonical write는 없었다.
3. attempt07은 기존 MeshPayload 0.2 polygon-corner UV를 사용해 seam vertex 복제를 제거하고 0면적 cap도
   없앴지만, source side가 inward인 상태에 outward cap을 수동 결합해 4,320 edge 중 320개의 shared-edge
   orientation이 일치하지 않았다. 기존 SceneSpec/MeshPayload/preflight/spatial audit SHA는 각각
   `8babcb91b44cd196c7d478d667262dd76441582aca63ef8add57a193ccf03b20`,
   `b70daabc5f393e039cdf4e6096dde35324991126b6edcce0c52609aa51ec48dc`,
   `929fc38d24edb827fe06edd9d4649cdd76cc715e287c1630808a08cf70dc17e6`,
   `1516c66140d048ed166a9cd19460e92858f9be4da559cfa8fe09bcbd9fba16fb`로 보존한다. proposal
   `4bad8cf9abfc491b894ae3d83a45be48890198055ac6586308fc4273498c359b`은 승인·발행·실행 전에 superseded했다.
4. 공통 loft compiler는 기존 fan이 nondegenerate이면 bytes를 유지하고, dense resampling으로 cap fan이
   퇴화할 때만 convex section 내부 center fan을 추가한다. section normal이 first→last progression과 반대이면
   faces만 반전한다. host focused 23/23, 실제 Blender 5.0.1 structural smoke 12/12를 통과했다.
5. attempt08은 attempt04의 exact StructureAuthoring을 수정된 compiler로 재컴파일하고 polygon-corner UV를
   exact topology/winding 위에 결합했다. SceneSpec SHA는
   `db111ebd0a263c20ef553e39ec1012078d31ad8bf6fe8244bccc798c81a5044d`, MeshPayload SHA는
   `513d5473181a2e3ce51a55c6f6c7da51dce43fb8e2c2b228ce149d420026eefa`, preflight SHA는
   `75eeafaf08ec06fdec01e83ff819d2f34c21508727214ab0e623919bff57add3`, spatial audit SHA는
   `c110b406c7a22310a00146339f979986b09800e59bd1a29e2abe4c84d453b2b9`다. 2,082 vertices, 2,240 faces,
   4,320 edge incidence 2/orientation balance 0, 0 degenerate face, 8,640 loop UV를 확인했다. texture map 직접
   inspection에서는 attempt03보다 밝은 base color와 longitudinal grain/knot variation을 확인했지만, reference보다
   저주파 대비와 풍화 균열감이 약하고 비교적 규칙적인 위험이 남았다. 승인된 V03 exact scope
   `ec090247635b469f0fb90782c5654247c3713eeaeae1533f09a4d031aa07cf26`로 primary만 실행했고 retry 없이
   기술 완료했다. exact beauty `2f6b30e6f601649b9eaf9ea136156b26e3743fb207ed6a07a05a7636ad0f9435`의
   source-bound review는 구조 3/4를 충족했지만 방향성 목재 표면을 major defect로 유지한다. 성공한 primary
   뒤의 동일 입력 technical retry는 닫혔고, 현재 계약은 새 시각 수정 회차 권한을 주지 않는다.
6. V04 exact scope로 attempt09 primary를 한 번 완료했다. 고정 관찰 4/4와 attempt08 대비 `improved`를
   source-bound 비인간 evidence로 기록했으며, 성공한 primary 뒤 technical retry는 닫았다. 이는 인간
   disposition이나 canonical/package 권한이 아니다.
7. exact material-conversion 및 package scope 승인으로 512px CPU conversion과 static-payload package/fresh
   clean import를 완료해 B의 계획된 최소 portable 경계를 닫았다. 이어 C 네 reference 전이도 완료했지만,
   이 격리 evidence는 E의 새 clean-baseline 캠페인 실적으로 재사용하지 않는다.
8. 인간 exact quality disposition, package acceptance, Activation 수락은 각각 실제 결과를 대상으로 별도 받는다.

### 최종 검증 후속

AQ `-RunBlender -SkipFullRegression -SkipLegacyGates` 게이트와 repository catalog 동기화는 통과했다.
최신 게이트의 Blender `1 skipped`와 focused `32 skipped`는 실행 성공으로 세지 않는다. benchmark는 synthetic fixture의
계약·metric 방향성 증거이며 실제 다섯 reference의 품질 증거가 아니다. 별도 V0.9 게이트는 V0.8 중복 gate를
생략했지만 vision을 포함한 전체 dev test와 실제 V0.9 package/clean-import/handoff를 통과했다. package manifest
SHA는 `29d20f588ac2e90267143819690ffc5aa7de5909566d2153af31aa8ec114f6a0`, round-trip validation SHA는
`be10e06b650bf8dd2a9aa1f0e9d198f3229dfd1c611bded5ab91a3df8c0eada3`, handoff manifest SHA는
`096dde0e0e964b8abc4e16e9ff7ef2d50476ae99dac4542c1567aed202e40f70`다. clean import는 bounds 오차
`0.0m`, semantic/material coverage `1.0`이며 6개 알려진 axis/unit/normal/tangent/UV 한계는 warning으로
남겼다.
이 gate 내부의 자동 approval 문자열은 격리 fixture의 테스트 입력일 뿐 실제 인간 approval이나 현재 자산
package acceptance가 아니다. dev-only gate 뒤에는 `uv sync --frozen --extra dev --extra vision`으로 환경을
유지했다. 과거 16개 anchor audit도 마지막으로 16/16 일치했고 기존 판정이나 Activation 권한을 만들지 않았다.
