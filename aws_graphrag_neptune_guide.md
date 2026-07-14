# AWS GraphRAG with Amazon Neptune — 완전 가이드

> **조사 기준** : AWS 공식 문서 및 AWS 블로그 기반 정리  
> **대상 서비스** : Amazon Bedrock Knowledge Bases GraphRAG + Amazon Neptune Analytics  
> **최종 업데이트** : 2026-07-15  

---

## 목차

1. [GraphRAG 개요](#1-graphrag-개요)
2. [핵심 AWS 서비스 구성](#2-핵심-aws-서비스-구성)
3. [Neptune Database vs Neptune Analytics](#3-neptune-database-vs-neptune-analytics)
4. [Neptune Analytics 핵심 개념 — m-NCU](#4-neptune-analytics-핵심-개념--m-ncu)
5. [구현 방법 3가지](#5-구현-방법-3가지)
6. [완전 관리형 구현 — Bedrock Knowledge Bases](#6-완전-관리형-구현--bedrock-knowledge-bases)
7. [인제스션 파이프라인 상세](#7-인제스션-파이프라인-상세)
8. [Neptune 그래프 노드 구조](#8-neptune-그래프-노드-구조)
9. [Entity 관계 추출 메커니즘](#9-entity-관계-추출-메커니즘)
10. [엣지(관계) 3종류 상세](#10-엣지관계-3종류-상세)
11. [크로스 도큐먼트 연결](#11-크로스-도큐먼트-연결)
12. [GraphRAG Toolkit — 3계층 Lexical Graph](#12-graphrag-toolkit--3계층-lexical-graph)
13. [openCypher 쿼리 예시](#13-opencypher-쿼리-예시)
14. [GraphRAG 검색 동작 흐름](#14-graphrag-검색-동작-흐름)
15. [임베딩 모델 및 그래프 구성 모델](#15-임베딩-모델-및-그래프-구성-모델)
16. [메타데이터 필터링 모범 사례](#16-메타데이터-필터링-모범-사례)
17. [CloudWatch 모니터링](#17-cloudwatch-모니터링)
18. [일반 RAG vs GraphRAG 비교](#18-일반-rag-vs-graphrag-비교)
19. [제한사항 및 주의사항](#19-제한사항-및-주의사항)
20. [추천 시작 구성](#20-추천-시작-구성)
21. [참고 문서](#21-참고-문서)

---

## 1. GraphRAG 개요

**GraphRAG**는 기존 벡터 기반 RAG에 **지식 그래프(Knowledge Graph)** 를 결합하여 LLM의 응답 품질을 향상시키는 기술입니다.

### 기존 RAG의 한계

| 한계 | 설명 |
|---|---|
| 관계 파악 불가 | 벡터 유사도 검색만으로는 엔티티 간 관계 표현 불가 |
| Multi-hop 추론 취약 | 여러 문서를 논리적으로 연결하는 추론 어려움 |
| 크로스 도큐먼트 연결 불가 | 서로 다른 문서에 흩어진 정보 통합 어려움 |

### GraphRAG가 해결하는 것

- 엔티티와 관계를 구조화하여 **복잡한 질의** 처리 가능
- 여러 문서를 논리적으로 연결하는 **Multi-hop 추론** 지원
- 할루시네이션 감소 및 **설명 가능한(Explainable) 응답** 생성
- 서로 참조하지 않는 문서들을 **공유 엔티티**로 자동 연결

### 적합한 사용 사례

- 법률 계약서, 연구 논문, 규정 준수 문서 분석
- 금융 보고서 간 연관 관계 분석 (헤드라인/테일윈드 등)
- 보안 위협 신호 연결 및 분석
- 공급망 리스크 분석
- 기술 문서 간 의존 관계 파악

---

## 2. 핵심 AWS 서비스 구성

| 서비스 | 역할 |
|---|---|
| **Amazon S3** | 원본 문서 저장소 (유일하게 지원되는 데이터 소스) |
| **Amazon Bedrock Knowledge Bases** | 완전 관리형 GraphRAG 파이프라인 오케스트레이션 |
| **Amazon Neptune Analytics** | 그래프 + 벡터 통합 저장 및 검색 엔진 |
| **Amazon Bedrock — LLM** | 엔티티 추출용 Graph Construction Model + 최종 응답 생성 |
| **Amazon Bedrock — Embedding** | 문서 청크 벡터 임베딩 생성 |
| **Amazon CloudWatch** | Neptune Analytics 성능 모니터링 |

### 서비스 전체 아키텍처

```
[S3 문서 (PDF/TXT/DOCX)]
        │
        ▼
[Bedrock Knowledge Bases]  ←──── Graph Construction Model (LLM)
        │  파싱 / 청킹 / 임베딩 / Entity 추출
        ▼
[Neptune Analytics]
   ├── 벡터 인덱스  (Chunk 임베딩)
   └── 그래프       (Document / Chunk / Entity 노드 + 엣지)
        │
        ▼  검색 시
[질문 벡터화] → [벡터 검색] → [그래프 순회] → [컨텍스트 보강]
        │
        ▼
[Bedrock LLM] ──→ 최종 응답
```

---

## 3. Neptune Database vs Neptune Analytics

| 구분 | Neptune Database | Neptune Analytics |
|---|---|---|
| **용도** | 대규모 OLTP 그래프 DB | 인메모리 분석용 그래프 엔진 |
| **아키텍처** | 디스크 기반, 서버리스 | **전부 메모리 상주** |
| **쿼리 언어** | Gremlin, SPARQL, openCypher | openCypher만 지원 (벡터 확장 포함) |
| **Bedrock GraphRAG 연동** | ❌ (구버전 LlamaIndex 방식만) | ✅ **공식 완전 관리형 연동** |
| **벡터 인덱스** | ❌ | ✅ 내장 지원 |
| **자동 스케일링** | ✅ 지원 | ❌ 수동 m-NCU 조정 필요 |
| **Pause(일시정지)** | ❌ | ✅ (정지 시 비용 90% 절감) |
| **스토리지 비용** | 별도 청구 | **무료** (메모리에 포함) |
| **그래프 알고리즘** | 제한적 | ✅ 다양한 내장 알고리즘 지원 |

> ⚠️ **Bedrock Knowledge Bases GraphRAG는 Neptune Analytics 전용입니다.**

---

## 4. Neptune Analytics 핵심 개념 — m-NCU

```
m-NCU (memory-optimized Neptune Capacity Unit)
= 1 GB 메모리 + 해당 컴퓨트 + 네트워크 자원 / 시간
```

### 지원 용량 및 처리 능력

| m-NCU | 메모리 | Worker 스레드 수 | 추천 사용 사례 |
|---|---|---|---|
| **32** | 32 GB | 8개 | POC, 소규모 테스트 (최근 추가, 가장 저렴) |
| **64** | 64 GB | 16개 | 개발 / 스테이징 |
| **128** | 128 GB | 32개 | 소규모 프로덕션 |
| **256** | 256 GB | 64개 | 중규모 프로덕션 |
| **4,096** | 4 TB | 1,024개 | 초대규모 |

> `Worker 스레드 수 = m-NCU ÷ 4`

### 비용 구조

```
비용 = m-NCU 수 × 시간당 단가 (리전별 상이)

항목별 정책:
  - 스토리지 / I/O 비용  : 무료
  - Pause 상태           : 정상 비용의 10%만 청구 (데이터/설정 보존)
  - 참고 예시 비용        : 약 $0.48/시간 (32 m-NCU 기준, us-east-1)
```

> 💡 사용하지 않는 시간에는 **Pause** 상태로 전환하여 비용 절약!

---

## 5. 구현 방법 3가지

| # | 방법 | 주요 도구 | 난이도 | 커스터마이징 수준 |
|---|---|---|---|---|
| **①** | **완전 관리형** | Bedrock Knowledge Bases + Neptune Analytics | ⭐ 쉬움 | 낮음 |
| **②** | **오픈소스 프레임워크** | LlamaIndex + Neptune DB/Analytics + Bedrock | ⭐⭐ 중간 | 높음 |
| **③** | **GraphRAG Toolkit** | AWS 공식 오픈소스 Python 라이브러리 | ⭐⭐⭐ 복잡 | 매우 높음 |

### 방법별 선택 기준

| 요구사항 | 추천 방법 |
|---|---|
| 빠른 POC, 최소 코드 | ① 완전 관리형 |
| 기존 그래프 DB 활용, 커스텀 관계 | ② LlamaIndex |
| 엔티티 타입 커스터마이징, 대규모 프로덕션 | ③ GraphRAG Toolkit |

---

## 6. 완전 관리형 구현 — Bedrock Knowledge Bases

### 콘솔 설정 단계 (방법 ①)

```
Step 1. AWS 콘솔 → Amazon Bedrock → Knowledge bases
Step 2. [Create] → "Knowledge Base with vector store" 선택
Step 3. KB 이름 및 설명 입력
Step 4. IAM 권한 설정 (자동 생성 또는 커스텀 역할)
Step 5. 데이터 소스: Amazon S3 선택 → S3 URI 입력
Step 6. 임베딩 모델 선택 (Titan Text Embeddings V2 권장)
Step 7. 벡터 DB: "Amazon Neptune Analytics (GraphRAG)" 선택
         ├── Quick create  : Neptune 리소스 자동 생성 [권장]
         └── Choose existing: 기존 Neptune 그래프 ARN 지정
Step 8. Graph Construction Model 선택 (Claude Haiku 4.5 / Amazon Nova 권장)
Step 9. [Create knowledge base] → 완료 후 [Sync] 실행
```

> ⚠️ Root 계정으로는 Knowledge Base 생성 불가. IAM 계정 필요.

### CLI — 데이터 소스 생성 예시

**input.json**
```json
{
  "dataSourceConfiguration": {
    "s3Configuration": {
      "bucketArn": "arn:aws:s3:::my-graphrag-bucket",
      "bucketOwnerAccountId": "123456789012",
      "inclusionPrefixes": ["documents/"]
    },
    "type": "S3"
  },
  "VectorIngestionConfiguration": {
    "contextEnrichmentConfiguration": {
      "type": "BEDROCK_FOUNDATION_MODEL",
      "bedrockFoundationModelConfiguration": {
        "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5",
        "enrichmentStrategyConfiguration": {
          "method": "CHUNK_ENTITY_EXTRACTION"
        }
      }
    }
  }
}
```

```bash
aws bedrock-agent create-data-source \
    --name graph_rag_source \
    --knowledge-base-id <KB_ID> \
    --cli-input-json "file://input.json"
```

### 지원 리전 (2026.07 기준)

| 리전 코드 | 리전명 |
|---|---|
| us-east-1 | US East (N. Virginia) |
| us-west-2 | US West (Oregon) |
| eu-central-1 | Europe (Frankfurt) |
| eu-west-2 | Europe (London) |
| eu-west-1 | Europe (Ireland) |
| ap-northeast-1 | Asia Pacific (Tokyo) |
| ap-southeast-1 | Asia Pacific (Singapore) |

---

## 7. 인제스션 파이프라인 상세

AWS 공식 블로그(`build-graphrag-applications-using-amazon-bedrock-knowledge-bases`) 기반의 **정확한 처리 흐름**:

```
[S3 문서 (PDF / TXT / DOCX)]
         │
         ▼
① 문서 파싱 & 청킹
   - fixed-size / semantic / hierarchical 선택 가능
   - 기본 청킹 권장 (hierarchical은 child chunk만 반환)
         │
         ▼
② 임베딩 생성
   - Titan Embeddings V2 / Cohere Embed 사용
   - 생성된 벡터 → Neptune Analytics 벡터 인덱스에 저장
         │
         ▼
③ ExtractChunkEntity 단계  ★ 핵심
   - Graph Construction Model (LLM) 이 각 Chunk 텍스트 처리
   - Entity 추출 : (이름, 타입, 설명)
   - Relation 추출 : (Subject, Relation, Object) 트리플 형태
         │
         ▼
④ Neptune Analytics Bulk Load API 로 일괄 적재
   - 노드  : Document, Chunk, Entity
   - 엣지  : PART_OF, HAS_ENTITY, RELATES_TO (커스텀)
   - 벡터  : Chunk 임베딩 동시 저장
         │
         ▼
⑤ 그래프 완성 및 벡터 인덱스 갱신
   - S3 문서 업데이트 시 Sync 재실행으로 증분 반영
```

---

## 8. Neptune 그래프 노드 구조

Bedrock이 자동으로 생성하는 **3가지 노드 타입**:

```
┌──────────────────────────────────────────────────┐
│             Neptune Analytics Graph               │
│                                                  │
│  ┌────────────────────┐                          │
│  │   Document Node    │                          │
│  │  - documentId      │                          │
│  │  - s3Uri           │                          │
│  │  - title           │                          │
│  └────────┬───────────┘                          │
│           │ ◄─── PART_OF ───┐                    │
│           │                 │                    │
│  ┌────────▼───────────┐     │                    │
│  │    Chunk Node      │─────┘                    │
│  │  - chunkId         │                          │
│  │  - text            │                          │
│  │  - embedding[]  ←── 벡터 인덱스               │
│  │  - documentId      │                          │
│  └────────┬───────────┘                          │
│           │  HAS_ENTITY                          │
│           ▼                                      │
│  ┌────────────────────┐   [RELATES_TO]           │
│  │   Entity Node      │ ──────────────► Entity   │
│  │  - name            │                          │
│  │  - type            │                          │
│  │  - description     │                          │
│  └────────────────────┘                          │
└──────────────────────────────────────────────────┘
```

| 노드 타입 | 역할 | 주요 속성 |
|---|---|---|
| **Document** | S3 원본 문서 단위 | `documentId`, `s3Uri`, `title` |
| **Chunk** | 분할된 텍스트 조각 + 벡터 임베딩 | `chunkId`, `text`, `embedding[]`, `documentId` |
| **Entity** | LLM이 추출한 개념 / 인물 / 조직 / 장소 등 | `name`, `type`, `description` |

---

## 9. Entity 관계 추출 메커니즘

### ExtractChunkEntity — LLM이 수행하는 작업

각 Chunk 텍스트를 Graph Construction Model에 전달하여 **트리플(Triple)** 형태로 추출합니다.

**입력 텍스트 예시:**
```
"Amazon Neptune supports openCypher query language.
 Neptune Analytics is optimized for in-memory graph analytics."
```

**LLM 추출 결과 (트리플):**
```
(Amazon Neptune)    ──[SUPPORTS]──────────────► (openCypher)
(Neptune Analytics) ──[IS_OPTIMIZED_FOR]──────► (in-memory graph analytics)
(Amazon Neptune)    ──[HAS_SERVICE]────────────► (Neptune Analytics)
```

### 트리플(Triple) 구조

```
  (Subject Entity)  ──[Relation Edge]──►  (Object Entity)
       주어                관계                목적어
```

### Entity 추출 결과물 예시

```
Entity: "Amazon Neptune"
  - type       : PRODUCT / SERVICE
  - description: AWS의 완전 관리형 그래프 데이터베이스 서비스

Entity: "openCypher"
  - type       : TECHNOLOGY / LANGUAGE
  - description: 프로퍼티 그래프용 오픈소스 쿼리 언어
```

### 관계명(Edge Label) 결정 방식

| 구현 방법 | 관계명 결정 | 커스터마이징 |
|---|---|---|
| Bedrock 완전 관리형 | LLM이 문맥에 따라 **동적으로 자동 결정** | ❌ 불가 |
| GraphRAG Toolkit | 도메인별 **커스텀 엔티티 타입 및 관계명** 정의 | ✅ 가능 |

---

## 10. 엣지(관계) 3종류 상세

### ① `PART_OF` — Chunk → Document 연결

```cypher
(chunk:Chunk)-[:PART_OF]->(doc:Document)
```

| 항목 | 내용 |
|---|---|
| 방향 | Chunk → Document |
| 목적 | 청크의 원본 문서 추적 (Lineage 보존) |
| 추가 속성 | 없음 |

---

### ② `HAS_ENTITY` — Chunk → Entity 연결

```cypher
(chunk:Chunk)-[:HAS_ENTITY]->(entity:Entity)
```

| 항목 | 내용 |
|---|---|
| 방향 | Chunk → Entity |
| 목적 | 해당 Chunk에서 언급된 Entity 연결 |
| 핵심 특성 | 같은 Entity가 여러 Chunk에서 언급 → **여러 HAS_ENTITY 엣지 생성** |
| 효과 | 서로 다른 문서 간 **크로스 도큐먼트 연결의 다리** 역할 |

---

### ③ `RELATES_TO` (커스텀 관계 엣지) — Entity ↔ Entity

```cypher
-- LLM이 문맥에 따라 동적으로 생성하는 관계 예시
(entityA:Entity)-[:SUPPORTS]──────────►(entityB:Entity)
(entityA:Entity)-[:ACQUIRED]──────────►(entityB:Entity)
(entityA:Entity)-[:PARTNERS_WITH]─────►(entityB:Entity)
(entityA:Entity)-[:LOCATED_IN]────────►(entityB:Entity)
(entityA:Entity)-[:BELONGS_TO]────────►(entityB:Entity)
(entityA:Entity)-[:IS_OPTIMIZED_FOR]──►(entityB:Entity)
```

| 항목 | 내용 |
|---|---|
| 방향 | 단방향 (left → right 고정) |
| 관계명 | LLM이 동사 형태로 동적 생성 |
| 데이터 모델 | Subject → Predicate → Object (트리플) |
| 커스터마이징 | Bedrock 완전 관리형은 불가, GraphRAG Toolkit은 가능 |

---

## 11. 크로스 도큐먼트 연결

GraphRAG의 가장 강력한 기능 — 서로 직접 참조하지 않는 두 문서가 **공유 Entity 노드를 통해 자동으로 연결**됩니다.

### 동작 원리

```
[문서 A: 공급업체 계약서]              [문서 B: 사고 보고서]
          │                                    │
     [Chunk A1]                           [Chunk B3]
          │  HAS_ENTITY                        │  HAS_ENTITY
          ▼                                    ▼
     [Entity: "삼성전자"] ◄──── 동일 노드 ────[Entity: "삼성전자"]
                             ↑
               두 문서가 같은 Entity를 언급하는 순간
               그래프 상에서 자동으로 연결됨!
```

### 실제 활용 예시

| 구분 | 내용 |
|---|---|
| **질문** | "삼성전자 공급 이슈가 우리 계약에 미치는 영향은?" |
| **일반 Vector RAG** | 두 문서를 별개로 처리 → 관계 파악 불가 |
| **GraphRAG** | Entity `삼성전자`를 통해 두 문서 자동 연결 → 통합 분석 응답 생성 |

### 크로스 도큐먼트 연결이 만들어지는 조건

1. 동일한 Entity 이름이 **서로 다른 문서의 Chunk**에서 추출될 것
2. 두 Chunk가 각각 해당 Entity 노드에 `HAS_ENTITY` 엣지로 연결될 것
3. Entity 노드가 **단일 노드로 공유** (중복 생성 아님)

---

## 12. GraphRAG Toolkit — 3계층 Lexical Graph

AWS 오픈소스 `graphrag-toolkit`이 사용하는 더 정교한 **3계층 구조** (Bedrock 완전 관리형보다 세밀한 제어 가능):

```
┌────────────────────────────────────────────────────────┐
│  Layer 1: Lineage Layer (출처 추적)                     │
│                                                        │
│  Source Node ──────────────────────► Chunk Node        │
│  (원본 문서 정보)                      (텍스트 조각)    │
│                                                        │
│  목적: 정보 계보(Lineage) 추적, 엔터프라이즈 검증       │
├────────────────────────────────────────────────────────┤
│  Layer 2: Entity-Relationship Layer (핵심 구조)         │
│                                                        │
│  Entity Node ──[RELATES_TO]────────► Entity Node       │
│  (추출된 엔티티)    (동적 관계)         (연결 엔티티)   │
│                                                        │
│  목적: 엔티티 간 관계 표현, 키워드 기반 Bottom-up 검색  │
├────────────────────────────────────────────────────────┤
│  Layer 3: Summarization Layer (의미 추상화)             │
│                                                        │
│  Topic Node → Statement Node → Fact Node               │
│  (문서 로컬)     (중간 추상화)    (글로벌 연결)         │
│                                                        │
│  목적: 추상화 수준별 정보 제공, 전역 크로스 도큐먼트 연결│
└────────────────────────────────────────────────────────┘
```

| 계층 | 포함 노드 | 주요 검색 역할 |
|---|---|---|
| **Lineage** | Source, Chunk | 출처 / 계보 추적 |
| **Entity-Relationship** | Entity, Relation Edge | 키워드 기반 Bottom-up 검색 |
| **Summarization** | Topic, Statement, Fact | 의미 기반 Top-down 검색 + 글로벌 연결 |

### GraphRAG Toolkit 빠른 시작 코드

```python
from graphrag_toolkit import LexicalGraphIndex
from graphrag_toolkit.storage import GraphStoreFactory, VectorStoreFactory
from llama_index.readers.web import SimpleWebPageReader

# Neptune Analytics + OpenSearch Serverless 연결
graph_store  = GraphStoreFactory.for_graph_store(
    'neptune-db://my-graph.cluster-xxxx.us-east-1.neptune.amazonaws.com'
)
vector_store = VectorStoreFactory.for_vector_store(
    'aoss://my-collection.us-east-1.aoss.amazonaws.com'
)

# 지식 그래프 인덱싱
graph_index = LexicalGraphIndex(graph_store, vector_store)
docs = SimpleWebPageReader(html_to_text=True).load_data(doc_urls)
graph_index.extract_and_build(docs, show_progress=True)
```

---

## 13. openCypher 쿼리 예시

Neptune Analytics는 **openCypher 언어만 지원**합니다.

### 그래프 스키마 전체 조회

```cypher
-- nodeLabels / edgeLabels / nodeLabelDetails / edgeLabelDetails / labelTriples 반환
CALL neptune.graph.pg_schema()
YIELD schema
RETURN schema
```

### 노드 라벨별 카운트

```cypher
CALL neptune.graph.pg_schema()
YIELD schema
WITH schema.nodeLabels AS nl
UNWIND collSort(nl) AS label
MATCH (n)
WHERE label IN labels(n)
RETURN label, COUNT(n) AS count
```

### Entity 간 관계 전체 조회

```cypher
MATCH (e1:Entity)-[r]->(e2:Entity)
RETURN e1.name AS 주어, type(r) AS 관계, e2.name AS 목적어
LIMIT 50
```

### 특정 Entity의 모든 관계 탐색

```cypher
MATCH (e:Entity {name: "Amazon Neptune"})-[r]->(related)
RETURN e.name, type(r), related.name, labels(related)
```

### Multi-hop 관계 추적 (2단계)

```cypher
MATCH (e:Entity {name: "Amazon Neptune"})
      -[r1]->(mid:Entity)
      -[r2]->(target:Entity)
RETURN e.name, type(r1), mid.name, type(r2), target.name
```

### Chunk에서 Entity로 역추적

```cypher
MATCH (c:Chunk)-[:HAS_ENTITY]->(e:Entity)-[r]->(e2:Entity)
WHERE c.chunkId = 'chunk_001'
RETURN e.name, type(r), e2.name
```

### 크로스 도큐먼트 — 공유 Entity로 연결된 문서 탐색

```cypher
MATCH (d1:Document)<-[:PART_OF]-(c1:Chunk)-[:HAS_ENTITY]->(e:Entity)
      <-[:HAS_ENTITY]-(c2:Chunk)-[:PART_OF]->(d2:Document)
WHERE d1 <> d2
RETURN e.name   AS 공유_엔티티,
       d1.title AS 문서1,
       d2.title AS 문서2
```

### 벡터 유사도 + 그래프 순회 하이브리드 검색

```cypher
CALL neptune.algo.vectors.topKByEmbedding(
    $queryEmbedding,
    {topK: 5, concurrentRequests: 4}
)
YIELD node AS chunk, score
MATCH (chunk)-[:HAS_ENTITY]->(entity:Entity)
RETURN chunk.text, score, collect(entity.name) AS entities
ORDER BY score DESC
```

---

## 14. GraphRAG 검색 동작 흐름

### 5단계 검색 프로세스

```
사용자 질문: "A사와 B사의 협력 관계는?"
         │
         ▼  ① 질문 벡터화
            임베딩 모델로 질문 텍스트를 벡터로 변환
         │
         ▼  ② 벡터 유사도 검색
            Neptune 벡터 인덱스에서 의미적으로 유사한
            Chunk 상위 K개 추출
         │
         ▼  ③ 그래프 순회 (Graph Traversal)
            Chunk ──HAS_ENTITY──► Entity 탐색
            Entity ──RELATES_TO──► 연결 Entity 확장
            확장된 Entity와 연결된 다른 문서 Chunk까지 수집
         │
         ▼  ④ 컨텍스트 보강
            관련 엔티티, 관계, 연결 Chunk 텍스트를
            통합하여 풍부한 컨텍스트 구성
         │
         ▼  ⑤ LLM 응답 생성
            보강된 컨텍스트 + 원본 질문 → LLM 입력
            → 더 정확하고 설명 가능한 최종 응답 출력
```

### 일반 RAG vs GraphRAG 검색 흐름 비교

```
[일반 RAG]
질문 ──► 벡터 검색 ──► 유사 Chunk K개 ──► LLM ──► 응답

[GraphRAG]
질문 ──► 벡터 검색 ──► 유사 Chunk K개
                               │
                          그래프 순회
                     (Entity 연결 자동 확장)
                               │
                    보강된 컨텍스트
                 (다문서 관계 포함, 풍부함)
                               │
                             LLM ──► 응답
```

---

## 15. 임베딩 모델 및 그래프 구성 모델

### 지원 임베딩 모델

| 모델명 | 벡터 차원 | 특징 |
|---|---|---|
| **Amazon Titan Text Embeddings V2** | 256 / 512 / **1024** | ✅ 권장 (비용 효율, floating-point) |
| **Cohere Embed** | 1024 | 다국어 강점 |
| **Amazon Titan Multimodal** | 1024 | 이미지 + 텍스트 동시 지원 |

> ⚠️ **임베딩 모델의 벡터 차원 수 = Neptune Analytics 벡터 인덱스 차원 수 (반드시 일치!)**  
> ⚠️ **Floating-point 벡터 임베딩 타입 권장**

### 지원 그래프 구성 모델 (Entity 추출용 LLM)

| 모델명 | 상태 | 비고 |
|---|---|---|
| Claude 3 Haiku | ⚠️ Legacy | 사용 가능하나 비권장 |
| **Claude Haiku 4.5** | ✅ 현재 지원 | 권장 |
| **Amazon Nova Lite / Micro / Pro** | ✅ 현재 지원 | 텍스트 입력 모달리티 지원 |

### Cross-Region Inference Profile ARN 형식

```
arn:aws:bedrock:<source-region>:<account-id>:inference-profile/<prefix>.<model-id>

예시:
arn:aws:bedrock:us-west-2:123456789012:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0
```

---

## 16. 메타데이터 필터링 모범 사례

### 메타데이터 파일 예시

S3에 문서와 **동일한 경로**에 `.metadata.json` 파일로 배치합니다.

```json
{
  "document_type": "contract",
  "department":    "engineering",
  "region":        "us-east",
  "created_date":  1704067200,
  "is_active":     true
}
```

> ⚠️ `list` 타입 메타데이터는 지원하지 않음  
> ⚠️ 숫자는 내부적으로 Double로 변환됨 (예: `2024` → `2024.0`)

### 지원 필터 타입

| 필터 연산자 | 설명 | 권장 여부 |
|---|---|---|
| `equals` | 정확히 일치 | ✅ 권장 |
| `in` / `notIn` | 목록 중 포함 / 미포함 | ✅ 권장 (목록은 작게 유지) |
| `greaterThan` / `lessThan` | 숫자 범위 비교 | ✅ 권장 (날짜는 epoch 숫자로) |
| `startsWith` | 문자열 시작 일치 | ⚠️ 성능 저하, 가능하면 회피 |
| `andAll` / `orAll` | 복합 필터 결합 | ✅ 권장 |

### Python SDK 필터 적용 예시

```python
retrieval_config = {
    "vectorSearchConfiguration": {
        "filter": {
            "andAll": [
                {"equals":      {"key": "document_type", "value": "contract"}},
                {"greaterThan": {"key": "created_date",  "value": 1704067200}},
                {"equals":      {"key": "is_active",     "value": True}}
            ]
        }
    }
}
```

### 메타데이터 설계 원칙

| 원칙 | 권장 방식 | 비권장 방식 |
|---|---|---|
| 계층 구조 | 속성 분리: `org`, `team`, `project` | 단일 문자열: `"org/team/project"` |
| 날짜 표현 | 숫자 epoch: `1704067200` | 문자열 날짜: `"2024-01-01"` |
| 카테고리 | 명시적 속성: `"document_type": "contract"` | prefix 매칭: `startsWith` |
| 목록 값 | `in` 필터로 소규모 목록 | 매우 큰 목록 |

---

## 17. CloudWatch 모니터링

### 핵심 모니터링 지표

| CloudWatch 지표 | 의미 | 대응 방법 |
|---|---|---|
| `NumQueuedRequestsPerSec` > 0 지속 | 처리 한계 도달, 큐 대기 발생 | **m-NCU 즉시 증설** |
| `NumThrottledRequestsPerSec` > 0 | 요청 거부 발생 | **m-NCU 즉시 증설** |
| 메모리 사용률 > 80% | 그래프 크기 한계 도달 | m-NCU 업사이징 |

### 모니터링 및 운영 팁

- Filter-heavy 워크로드: m-NCU를 **여유 있게** 설정 (Worker 스레드 부족 방지)
- `NumQueuedRequestsPerSec`이 지속적으로 0보다 크면 → 스케일 업 신호
- m-NCU 조정은 **무중단 리사이징** 가능
- 사용하지 않는 시간에는 **Pause** → 비용 90% 절감

---

## 18. 일반 RAG vs GraphRAG 비교

| 비교 항목 | 일반 RAG | GraphRAG |
|---|---|---|
| **검색 방식** | 벡터 유사도만 | 벡터 + 그래프 관계 순회 |
| **다문서 추론** | ❌ 취약 | ✅ 강력 (Multi-hop) |
| **엔티티 관계 파악** | ❌ 불가 | ✅ 자동 추출 및 연결 |
| **크로스 도큐먼트 연결** | ❌ 불가 | ✅ 공유 Entity로 자동 연결 |
| **설명 가능성** | 낮음 | 높음 (관계 추적 가능) |
| **할루시네이션** | 상대적으로 많음 | 상대적으로 적음 |
| **구현 복잡도** | 낮음 | 높음 |
| **인프라 비용** | 저렴 | 상대적으로 고비용 |
| **인제스션 속도** | 빠름 | 느림 (LLM 추출 단계 추가) |
| **적합한 데이터** | 독립적 문서 | 관계형 / 복잡한 연결 문서 |

---

## 19. 제한사항 및 주의사항

| 제한 항목 | 상세 내용 |
|---|---|
| **데이터 소스** | S3만 지원 (RDS, DynamoDB, Confluence 등 불가) |
| **파일 수** | 기본 최대 1,000개 / 데이터소스 (최대 10,000개 증가 요청 가능) |
| **자동 스케일링** | ❌ 미지원 — 수동 m-NCU 조정 필요 |
| **청킹 전략** | Hierarchical 청킹 사용 시 child chunk만 반환 (parent chunk 미반환) |
| **그래프 구성 커스터마이징** | ❌ 미지원 (완전 관리형 방식) |
| **엔티티 타입 지정** | ❌ LLM이 자동 결정 (완전 관리형 방식) |
| **KB 생성 계정** | Root 계정 사용 불가 — IAM 계정 필요 |
| **삭제 순서** | ① Knowledge Base 먼저 삭제 → ② Neptune Analytics 그래프 삭제 (순서 반드시 준수) |
| **임베딩 차원** | 임베딩 모델 차원 수 = Neptune 벡터 인덱스 차원 수 (반드시 일치) |
| **임베딩 타입** | Floating-point 벡터 권장 |
| **비용 주의** | KB 삭제 후에도 Neptune 그래프 수동 삭제 전까지 과금 지속 |

---

## 20. 추천 시작 구성

### POC / 개발 환경

```
📁 S3 버킷
   ├── /documents/   ← 문서 업로드 (PDF, TXT, DOCX)
   └── /metadata/    ← .metadata.json (선택)

🔱 Neptune Analytics
   └── 32 m-NCU      ← POC 시작 (필요 시 업사이징)

🤖 Bedrock 모델 구성
   ├── 임베딩 모델       : Amazon Titan Text Embeddings V2 (1024차원)
   ├── 그래프 구성 모델  : Claude Haiku 4.5 or Amazon Nova Lite
   └── 응답 생성 모델    : Claude 3.5 Sonnet (권장)
```

### 프로덕션 환경

```
📁 S3 버킷 (폴더별 1,000개 파일 분할)
   ├── /dept-a/documents/
   └── /dept-b/documents/

🔱 Neptune Analytics
   ├── 128 m-NCU 이상
   └── CloudWatch 알람 설정
       ├── NumQueuedRequestsPerSec > 0 지속 → SNS 알람
       └── NumThrottledRequestsPerSec > 0  → 즉시 증설

🤖 Bedrock 모델 구성
   ├── 임베딩 모델       : Amazon Titan Text Embeddings V2 (1024차원)
   ├── 그래프 구성 모델  : Amazon Nova Pro (최신, 고품질 추출)
   └── 응답 생성 모델    : Claude 3.5 Sonnet

🔐 보안 구성
   ├── Neptune        : Private Subnet (VPC 내부)
   ├── IAM            : 최소 권한 원칙 (Least Privilege)
   ├── 암호화         : S3 + Neptune KMS CMK 적용
   ├── 감사 로그      : CloudTrail + VPC Flow Logs 활성화
   └── PII 처리       : Comprehend + Macie로 민감 데이터 태깅/마스킹
```

---

## 21. 참고 문서

| 문서 제목 | URL |
|---|---|
| Bedrock GraphRAG 공식 문서 | https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-graphs.html |
| Bedrock GraphRAG 콘솔 생성 가이드 | https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-graphs-build.html |
| Neptune Analytics 공식 문서 | https://docs.aws.amazon.com/neptune-analytics/latest/userguide/ |
| Neptune Analytics 벡터 유사도 | https://docs.aws.amazon.com/neptune-analytics/latest/userguide/vector-similarity.html |
| Neptune Analytics 프로퍼티 그래프 스키마 | https://docs.aws.amazon.com/neptune-analytics/latest/userguide/custom-algorithms-property-graph-schema.html |
| Neptune GraphRAG 메타데이터 필터링 Best Practices | https://docs.aws.amazon.com/neptune-analytics/latest/userguide/best-practices-graphrag-filters.html |
| Bedrock GraphRAG GA 발표 블로그 | https://aws.amazon.com/blogs/machine-learning/announcing-general-availability-of-amazon-bedrock-knowledge-bases-graphrag-with-amazon-neptune-analytics |
| GraphRAG 애플리케이션 구축 가이드 블로그 | https://aws.amazon.com/blogs/machine-learning/build-graphrag-applications-using-amazon-bedrock-knowledge-bases |
| Neptune + Bedrock Knowledge Graph 블로그 | https://aws.amazon.com/blogs/database/using-knowledge-graphs-to-build-graphrag-applications-with-amazon-bedrock-and-amazon-neptune |
| GraphRAG Toolkit GitHub (오픈소스) | https://github.com/awslabs/graphrag-toolkit |
| GraphRAG Toolkit 소개 블로그 | https://aws.amazon.com/blogs/database/introducing-the-graphrag-toolkit |
