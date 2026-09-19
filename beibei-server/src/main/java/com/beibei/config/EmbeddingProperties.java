package com.beibei.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.Locale;

/**
 * 向量化相关配置。
 *
 * <p>⚠️ 集合名的推导规则**必须与 Python 侧完全一致**，否则 Java 记录的名字
 * 和 Milvus 里真实的集合对不上（见 {@code app/config.py} 的 {@code chunk_collection}）。
 *
 * <p>规则：{@code {prefix}_{模型名最后一段，小写，'-' 和 '.' 换成 '_'}}
 * <br>例：{@code BAAI/bge-m3} → {@code bb_chunk_bge_m3}
 */
@ConfigurationProperties(prefix = "beibei.embedding")
public record EmbeddingProperties(
        String defaultModel,
        String collectionPrefix,
        String partitionPrefix
) {
    public EmbeddingProperties {
        if (defaultModel == null || defaultModel.isBlank()) {
            defaultModel = "BAAI/bge-m3";
        }
        if (collectionPrefix == null || collectionPrefix.isBlank()) {
            collectionPrefix = "bb_chunk";
        }
        if (partitionPrefix == null || partitionPrefix.isBlank()) {
            partitionPrefix = "kb_";
        }
    }

    /** 模型名归一化：BAAI/bge-m3 → bge_m3 */
    public static String modelKey(String model) {
        String shortName = model == null ? "" : model.substring(model.lastIndexOf('/') + 1);
        return shortName.toLowerCase(Locale.ROOT).replace('-', '_').replace('.', '_');
    }

    /** 由模型名推导集合名 */
    public String collectionOf(String model) {
        return collectionPrefix + "_" + modelKey(model == null ? defaultModel : model);
    }

    /** 默认集合名 */
    public String defaultCollection() {
        return collectionOf(defaultModel);
    }

    /** 知识库分区名 */
    public String partitionOf(Long kbId) {
        return partitionPrefix + kbId;
    }
}
