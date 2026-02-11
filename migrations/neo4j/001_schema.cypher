// AI Store Manager - Neo4j Schema
// Version: 001
// Date: 2026-02-11

// ============================================================
// Uniqueness constraints
// ============================================================
CREATE CONSTRAINT product_id IF NOT EXISTS
FOR (p:Product) REQUIRE p.product_id IS UNIQUE;

CREATE CONSTRAINT population_name IF NOT EXISTS
FOR (pop:Population) REQUIRE pop.name IS UNIQUE;

CREATE CONSTRAINT scenario_name IF NOT EXISTS
FOR (s:Scenario) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT symptom_name IF NOT EXISTS
FOR (sym:Symptom) REQUIRE sym.name IS UNIQUE;

CREATE CONSTRAINT faq_id IF NOT EXISTS
FOR (f:FAQ) REQUIRE f.faq_id IS UNIQUE;

// ============================================================
// Vector indexes (for Hybrid Search)
// ============================================================
CREATE VECTOR INDEX product_embedding_index IF NOT EXISTS
FOR (p:Product) ON (p.embedding)
OPTIONS {
    indexConfig: {
        `vector.dimensions`: 1024,
        `vector.similarity_function`: 'cosine'
    }
};

CREATE VECTOR INDEX faq_embedding_index IF NOT EXISTS
FOR (f:FAQ) ON (f.question_embedding)
OPTIONS {
    indexConfig: {
        `vector.dimensions`: 1024,
        `vector.similarity_function`: 'cosine'
    }
};

// ============================================================
// Full-text indexes (for keyword search)
// ============================================================
CREATE FULLTEXT INDEX product_fulltext IF NOT EXISTS
FOR (p:Product) ON EACH [p.name, p.description, p.category];

CREATE FULLTEXT INDEX faq_fulltext IF NOT EXISTS
FOR (f:FAQ) ON EACH [f.question, f.answer];

// ============================================================
// Seed: Population nodes
// ============================================================
MERGE (:Population {name: '老年人'});
MERGE (:Population {name: '高血压患者'});
MERGE (:Population {name: '糖尿病患者'});
MERGE (:Population {name: '孕妇'});
MERGE (:Population {name: '儿童'});
MERGE (:Population {name: '心律不齐患者'});
MERGE (:Population {name: '成年人'});

// ============================================================
// Seed: Scenario nodes
// ============================================================
MERGE (:Scenario {name: '日常血压监测'});
MERGE (:Scenario {name: '血糖管理'});
MERGE (:Scenario {name: '感冒护理'});
MERGE (:Scenario {name: '外伤处理'});
MERGE (:Scenario {name: '居家康复'});
MERGE (:Scenario {name: '婴儿护理'});

// ============================================================
// Relationship types reference (no DDL needed, documented here):
//
// (Product)-[:SUITABLE_FOR {confidence: float}]->(Population)
// (Product)-[:CONTRAINDICATED_FOR {reason: string}]->(Population)
// (Product)-[:USED_IN]->(Scenario)
// (Product)-[:OFTEN_BOUGHT_WITH {support, confidence, lift, order_count}]->(Product)
// (Product)-[:UPGRADE_TO {reason: string}]->(Product)
// (Product)-[:ALTERNATIVE_TO {similarity: float}]->(Product)
// (Product)-[:HELPS_WITH]->(Symptom)
// (FAQ)-[:ANSWERS]->(Product)
// ============================================================
