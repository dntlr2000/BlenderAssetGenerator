> 2026-09-30 프로젝트 보존용 열람본. 아래 평가는 당시 f55/0.9.0 상태의 기록이며 v0.9.1 검증으로 재분류하지 않습니다. 최신 종료·재개 기준은 [HANDOFF_KO.md](../HANDOFF_KO.md)에 있습니다. 원본의 내용은 보존하고 링크만 프로젝트 보존본으로 연결했습니다.

# GitHub main → 로컬 HEAD: 변경별 사용자 가치 검토

기준: `9759cd4d380cb1c9a1ec0e2085e08a8c35e2657c` → `f55e739ec072b40dc2ed9c408292899087ca7ccb`. 이번 문서는 분류·제안이며 commit, cherry-pick, push, rollback을 수행하지 않는다. 각 행은 실제 Git log와 변경 경로, 관련 코드·회귀/캠페인 기록을 함께 읽은 검토다. 검사 수나 commit 수는 품질 KPI가 아니다.

전체 파일별 diff와 full SHA는 [STATE_AUDIT.json](E:/CodexValidation/rf-reassessment-20260929-run01/STATE_AUDIT.json), 실제 결과/한계는 [본문](E:/CodexValidation/rf-reassessment-20260929-run01/REPORT_KO.md)에 있다. 아래 “회귀/검증”은 기존 실행 근거이며 이번에 새 검사를 돌린 것이 아니다.

| 순서·commit·날짜 | 가치 범주 | 출발 문제 | 변경·효과 근거 | 적용 범위·비용·판단 |
| --- | --- | --- | --- | --- |
| 1. `f7226f1` · 2026-09-02 | 관리 | Activation outcome·인간 판단·adapter terminal 연결 누락 | 캠페인 적격을 정확한 source/receipt로 분리. 직접 형상 효과 없음 | 자동 캠페인 운영에 한정; registry/index/schema 복잡성 큼 |
| 2. `84e5858` · 2026-09-02 | 관리 | 로컬 AQ profile publication 경계 | guarded publication 추가. 일반 asset 제작 기능이 아님 | 실험적 활성화에 한정; 일반 기본 도입 보류 |
| 3. `b9a314f` · 2026-09-02 | 관리 | IQ 이후 인간 review 미수용 종료 의미 | human review terminal 보강. 인간 미수용을 기술 성공과 구분 | 의미 보존 유효; 외관 개선으로 세지 않음 |
| 4. `b87c250` · 2026-09-02 | 생성 | source manifest 동기화 | 저장소 projection 갱신 | 독립 품질 이득 없음 |
| 5. `4bb2ce3` · 2026-09-02 | 버그 | GLTF split normal 직렬화 오차의 거짓 실패 | 허용오차를 제한해 정상 교환을 검사 | GLTF에 유용; 실제 normal 오류를 허용하지 않는 회귀 필요 |
| 6. `cf06d3b` · 2026-09-02 | 버그 | bounded GLTF normal 비교의 후속 경계 | 앞선 normal 비교를 보완 | 같은 문제의 후속 수정; 중복 이득으로 합산 금지 |
| 7. `c655386` · 2026-09-02 | 생성 | file manifest 동기화 | 생성 파일 갱신 | 독립 품질 이득 없음 |
| 8. `7359ce7` · 2026-09-03 | 평가 | 높은 IQ와 평평한 내부 외관 공존 | edge/명암/고주파 visibility gate. 실제 flat 결과를 막음 | 3D 구조 정답 판정은 아님; texture 복잡도 오인 주의 |
| 9. `f6830b7` · 2026-09-03 | 버그·관리 | 긴 Windows 경로와 terminal recovery 실패 | 경로 및 종료 복구 계약 보강 | Windows/AQ에 유효; 상태 분기 비용 추가 |
| 10. `42aa7c7` · 2026-09-03 | 버그·검증 | GLB corner 정밀도와 deep provenance 경계 | corner 비교와 긴 provenance 경로 확인 | 같은 납품 문제 계열. 미세 오차 검증을 형상 개선으로 세지 않음 |
| 11. `5e5b172` · 2026-09-03 | 버그 | portable conversion 중 deep shader 경로 손실 | 긴 shader 의존 경로 보존 | 기술 5/5 뒤에도 Wood 구조 미달. 납품 신뢰성 이득 |
| 12. `ad4e5e8` · 2026-09-05 | 저작·평가·관리 | flat Wood 및 결함별 수정 루프 부재 | 구조 가설·finding·comparison·저작 전략. A~D 격리 실증의 중심 | 실제 국소 개선 있음; 큰 복합 변경이며 일반 Standard 대비 효과 미입증 |
| 13. `2da54cb` · 2026-09-05 | 버그 | AQ Blender input 긴 경로 | 확장 경로 지원 | Windows 특화. d0da720에서 범위 재조정 |
| 14. `d0da720` · 2026-09-05 | 버그 | 확장 경로 지원의 지나치게 넓은 적용 | Blender input path 적용 범위를 제한 | 앞선 수정의 교정; 별도 외관 이득 아님 |
| 15. `2ae76d2` · 2026-09-05 | 버그 | structural reentry baseline blend 역할 불일치 | 재진입 시 올바른 baseline 역할 결속 | AQ 수정 신뢰성. Standard 전체 품질 개선 주장 불가 |
| 16. `69db7a1` · 2026-09-05 | 생성 | planner 수정 뒤 manifest 불일치 | repository manifest 갱신 | 독립 품질 이득 없음 |
| 17. `1899ce9` · 2026-09-05 | 관리·버그 | fidelity preview extension의 제한 | preview 경로 일반화 | ac4/07과 연속된 통합 작업. 일반 이득 별도 미입증 |
| 18. `ac4b6de` · 2026-09-05 | 관리·버그 | preview dependency 결속 누락 | preview 의존성 binding | 기존 preview 작업 후속. 증거 관리 복잡성 |
| 19. `07efa1a` · 2026-09-05 | 관리·버그 | preview runtime 결속 누락 | runtime binding 보완 | 동일 기능의 마무리; 세 commit을 세 품질 향상으로 세지 않음 |
| 20. `b617bae` · 2026-09-06 | 버그 | IQ reentry route 보존 실패 | 통합 품질 수정 경로 유지 | AQ 사용 시 필요; 일반 시각 우월성 근거 아님 |
| 21. `e37f230` · 2026-09-07 | 수정·관리 | QA 결함과 수정 단계의 인과 연결 부족 | 구조·국소·재질의 원인별 재진입 | 틀린 단계 재시도 감소 목적. 전체 시간 절감은 미입증 |
| 22. `b407d18` · 2026-09-07 | 버그·평가 | parametric policy 후조건 미검증 | 정해진 parameter 수정 후 postcondition 확인 | 잘못된 promotion 방지. 검증 유지 가치 |
| 23. `c8b1507` · 2026-09-08 | 관리 | 초기 authoring 비용 부족 | 초기 AQ 비용의 exact planning | 후속 finite epoch와 연속. 예산 계산 자체는 외관 개선 아님 |
| 24. `47e3928` · 2026-09-08 | 평가 | assembly bbox overlap 누락 | bounded overlap 검증 추가 | 거친 접촉 진단. 실제 접합/semantic 구조 정답 보장 아님 |
| 25. `a680633` · 2026-09-09 | 운영 | 과거 scratch와 저장공간 누적 | bounded storage retention 및 gate receipt | 이전 약 28.30GB 확보는 운영 이득. 형상 품질과 분리 |
| 26. `3956274` · 2026-09-09 | 버그·관리 | Laser funding 오류가 일반 기술 예외로 종료 | geometry policy 이전 funding 분류 | 원인 명확화·안전 중단. Laser 시각 개선 증거 아님 |
| 27. `03f5b93` · 2026-09-09 | 관리 | 필수 correction 비용 부족·소비 리셋 위험 | reference-bound finite correction budgets | 필요 비용 보존; epoch·lifetime 경계 유지비 증가 |
| 28. `668aec4` · 2026-09-10 | 관리·버그 | skill 진입점 exact funding 전달 누락 | 기존 예산 계약을 실제 진입점에 전달 | 관리 기능의 통합 보완 |
| 29. `07555be` · 2026-09-10 | 버그·검증 | source-bound geometry preflight·nested gate parameter 누락 | 검증 경계 및 parameter 전달 보강 | 유효 검증 기능. 수행된 gate와 실제 자산 성공 구분 |
| 30. `e93eea7` · 2026-09-11 | 버그·관리 | material closure 실행 profile·회차 binding 문제 | immutable round와 실행 profile 정합성 | AQ/closure에 유용; 복수 receipt/round 관리 비용 |
| 31. `1a07abc` · 2026-09-16 | 버그·관리 | material controller 준비 권한·resume 결속 문제 | 권한 준비와 재개 binding 보강 | 재개 안전성. 새 외관 기능 아님 |
| 32. `8e66fa1` · 2026-09-16 | 버그 | structural reentry 후 closure·deep Blender 경로 오류 | 재저작 뒤 재질 의존성과 경로 정합성 | 실제 수정 루프의 통합 수선. 테스트 범위 증가 |
| 33. `df8b151` · 2026-09-16 | 버그·평가 | historical QA closure 혼합·reference mask seed 오염 | 과거 closure 해석 보존·mask seed 분리 | 평가 신뢰성. 기존 QA를 새 점수로 재분류하지 않음 |
| 34. `0feae89` · 2026-09-19 | 평가 | reference segmentation의 불명확한 영역 | reference-only exact trimap constraint | 특정 사진 비교에 유효. mask 편향·저작 부담; 기본 사용 확대 보류 |
| 35. `493f934` · 2026-09-19 | 평가 | 비교 조명 조건 불명확 | camera-bound explicit comparison lighting | 같은 조건 증거 강화. 조명 개선을 형상 개선으로 계산 금지 |
| 36. `24632c6` · 2026-09-20 | 저작 | 자유 단면·파손 형상의 제한 | bounded triangulated shell로 구조 저작 | Plastic/Rust scope 납품에 사용. shell 자체의 일반 품질 효과는 미입증 |
| 37. `aa4e9f0` · 2026-09-28 | 관리 | 매 scope exact 승인 반복 | finite parent delegation으로 child scope 자동 처리 | 현재 2개 child 실행. 장기 개입 감소 미입증; 현재 source 연결 제약 발생 |
| 38. `aa22b13` · 2026-09-28 | 버그·관리 | Git archive LF/CRLF source hash 차이 | 텍스트 line ending 동등성 범위 처리 | 위임 기능 후속 호환성. immutable snapshots 제외 |
| 39. `ab39d9b` · 2026-09-29 | 관리·버그 | mandate 변경으로 strategy 소비 누락 위험 | 이전 전략 이력 승계 | anti-loop 의미 보존. 계보/slot 제약 유지비 |
| 40. `f55e739` · 2026-09-29 | 형상 버그 | multi_loop 내부 측면 중복 반전·Y축 방향 | 제품 메서드 1개와 직접 회귀 검사; 실제 Blender 19 fixture 검증 | 유지 가치 높음. 수정 후 실제 Rust 완성·current-baseline 시각 성과는 없음 |

## 범주별 유지보수 규모

| 영역 | 파일 수 | 추가 lines | 삭제 lines |
| --- | ---: | ---: | ---: |
| docs / skills / config | 33 | 2,705 | 84 |
| generated projection | 2 | 444 | 170 |
| schemas | 67 | 18,244 | 2 |
| scripts | 13 | 706 | 57 |
| source | 116 | 19,207 | 877 |
| tests | 77 | 15,137 | 105 |

Line 수는 생성 schema·검사·문서를 포함한다. 실행 코드의 품질이나 실제 유지보수 시간을 뜻하지 않는다. 서로 의존하는 변경을 단순히 한 행씩 분리 적용할 수 있다고 가정하지 않는다.

## 선별 제안

- 유지 가치가 높은 것: 재현된 mesh winding, Windows 긴 경로, GLTF 정밀도 비교, 올바른 source/receipt 검증·promotion 후조건. 해당 경로를 사용하는 사람에게 실패 예방의 직접 가치가 있다.
- 효과 확인이 필요한 것: reference 가설·시각 finding을 활용한 자동 수정, 새로운 구조 전략과 shell 저작, trimap·lighting 정책. 일부 자산에서는 개선됐지만 기존 Standard보다 평균적으로 유리한지는 확인되지 않았다.
- 일반 기본 도입을 보류할 것: 전체 5자산 Activation 실증, 추가 parent/epoch, source 변경마다 기존 자산부터 다시 증명하는 운영을 일반 단일 자산 사용의 필수 경로로 삼는 것.

기존 안전 검사와 증거 보존은 유효하다. 이를 삭제하자는 제안이 아니라, 실제 납품 요구와 무관한 프레임워크 확장을 중단하자는 제안이다.
