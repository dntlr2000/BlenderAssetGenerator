# Skill Orchestration KPI

## 사용자 편의성

- Standard 사용자 진입 skill 수: 1
- AQ 사용자 진입 skill 수: 1
- approval 뒤 다음 단계 재설명 필요 횟수: 목표 0
- 정상 AQ autonomous routine user decision 추가 횟수: 목표 0; genuine escalation 제외

## 일관성·복구

- route 결정의 exact source-state hash coverage: 100%
- 실행 receipt의 before/after immutable snapshot coverage: 100%
- receipt predecessor chain coverage: 첫 receipt 제외 100%
- live skill 변경 후 snapshot resume 성공률: valid evidence 기준 100%
- tamper/path escape/unknown route fail-closed 비율: 100%

## Standard 품질 흐름

- geometry/material 변경 뒤 fresh V0.6 QA 실행률: 100%
- `smart` skip의 MaterialImpactReport coverage: 100%
- specialized approval bypass: 0
- implicit failed retry: 0
- 기본 새 자산에서 비요청 V0.7 package 생성: 0

## AQ 안전성

- technical failure로 생성된 user approval request: 0
- policy authorization을 user approval로 기록한 건수: 0
- destination project write: 0
- repository-created Codex task/background-after-exit claim: 0
- review bundle을 production package로 분류한 건수: 0

## 활성화 판정

fixture와 schema 통과는 implementation readiness일 뿐 activation evidence가 아닙니다. AQ v2 status 변경은 clean source baseline, 대표 실제 자산 campaign, Blender 5.0.1 evidence, human acceptance와 별도 activation writer가 모두 있어야 합니다.

