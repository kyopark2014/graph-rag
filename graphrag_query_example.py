"""
Bedrock Knowledge Base GraphRAG (Neptune Analytics)에 저장된 그래프를
직접 조회 + 시각화하는 예제 스크립트

사전 준비
---------
1) KB 콘솔 > Vector store 설정에서 Neptune Analytics graph-identifier(예: g-xxxxxxxx) 확인
2) IAM 권한: neptune-graph:ReadDataViaQuery (최소), 필요시 GetGraph 등
3) pip install boto3 networkx matplotlib

사용 방법
---------
python graphrag_query_example.py --graph-id g-xxxxxxxx --region us-east-1
"""

import argparse
import json
import boto3
import networkx as nx
import matplotlib.pyplot as plt


def fetch_graph_sample(graph_id: str, region: str, limit: int = 100):
    """Neptune Analytics graph에서 노드-관계 샘플을 openCypher로 조회"""
    client = boto3.client("neptune-graph", region_name=region)

    # 전체 그래프가 클 수 있으므로 LIMIT을 걸어 일부만 조회 (탐색적 조회 권장)
    query = f"MATCH (a)-[r]->(b) RETURN a, r, b LIMIT {limit}"

    resp = client.execute_query(
        graphIdentifier=graph_id,
        queryString=query,
        language="OPEN_CYPHER",
    )

    # 응답은 stream(bytes) 형태이므로 읍어서 JSON 라인 단위로 파싱
    payload = resp["payload"].read().decode("utf-8")
    records = [json.loads(line) for line in payload.splitlines() if line.strip()]
    return records


def build_and_draw(records, out_path="graphrag_visualization.png"):
    G = nx.DiGraph()

    for rec in records:
        a = rec.get("a", {})
        b = rec.get("b", {})
        r = rec.get("r", {})

        a_id = a.get("~id", str(a))
        b_id = b.get("~id", str(b))
        a_label = ",".join(a.get("~labels", ["Node"]))
        b_label = ",".join(b.get("~labels", ["Node"]))
        r_label = r.get("~type", "REL")

        G.add_node(a_id, label=a_label)
        G.add_node(b_id, label=b_label)
        G.add_edge(a_id, b_id, label=r_label)

    pos = nx.spring_layout(G, seed=42, k=1.0)
    plt.figure(figsize=(12, 9))

    labels = nx.get_node_attributes(G, "label")
    unique_types = sorted(set(labels.values()))
    palette = ["#FF9900", "#E63946", "#457B9D", "#2A9D8F", "#8338EC"]
    color_map = {t: palette[i % len(palette)] for i, t in enumerate(unique_types)}
    node_colors = [color_map[labels.get(n, "Node")] for n in G.nodes]

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=1200, alpha=0.9)
    nx.draw_networkx_labels(G, pos, font_size=7)
    nx.draw_networkx_edges(G, pos, arrowstyle="->", arrowsize=12, edge_color="#999999")
    edge_labels = nx.get_edge_attributes(G, "label")
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=6)

    plt.title("Bedrock KB GraphRAG - Neptune Analytics Graph")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph-id", required=True, help="Neptune Analytics graph identifier (g-xxxx)")
    parser.add_argument("--region", required=True, help="AWS region, e.g. us-east-1")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    records = fetch_graph_sample(args.graph_id, args.region, args.limit)
    print(f"조회된 관계(edge) 수: {len(records)}")
    build_and_draw(records)
