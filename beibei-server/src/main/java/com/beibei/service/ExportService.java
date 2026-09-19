package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.dto.QuestionDto;
import com.beibei.entity.Question;
import com.beibei.entity.QuestionOption;
import com.beibei.mapper.QuestionMapper;
import com.beibei.mapper.QuestionOptionMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 题库导出。
 *
 * <p>三种格式各有用途：
 * <ul>
 *   <li><b>Anki (TSV)</b> —— 直达 Anki「导入文件」，通勤时手机背</li>
 *   <li><b>CSV</b> —— Excel 直接打开（带 UTF-8 BOM，否则中文乱码）</li>
 *   <li><b>JSON</b> —— 全量字段，用于迁移或二次加工</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ExportService {

    private final QuestionMapper questionMapper;
    private final QuestionOptionMapper optionMapper;
    private final QuestionService questionService;
    private final ObjectMapper objectMapper;

    /** 导出结果：文件名 + 内容 */
    public record ExportFile(String filename, String contentType, byte[] content) {
    }

    /** 题型 → 导出时的分组名 */
    private static String typeLabel(Integer qType) {
        return QuestionDto.typeName(qType);
    }

    public ExportFile exportQuestions(Long kbId, Integer status, String format, String kbName) {
        var query = Wrappers.<Question>lambdaQuery()
                .eq(kbId != null, Question::getKbId, kbId)
                .eq(status != null, Question::getStatus, status)
                .orderByAsc(Question::getQType)
                .orderByAsc(Question::getId);
        List<Question> questions = questionMapper.selectList(query);
        if (questions.isEmpty()) {
            // 空导出也生成文件，前端能提示「没有可导出的题目」
        }

        List<Long> ids = questions.stream().map(Question::getId).toList();
        Map<Long, List<QuestionOption>> optionMap = ids.isEmpty() ? Map.of()
                : optionMapper.selectList(Wrappers.<QuestionOption>lambdaQuery()
                        .in(QuestionOption::getQuestionId, ids)
                        .orderByAsc(QuestionOption::getSortOrder))
                .stream().collect(Collectors.groupingBy(QuestionOption::getQuestionId));
        Map<Long, List<com.beibei.dto.DocDto.TagBrief>> tagMap = questionService.tagBriefsOf(ids);

        String safeName = (kbName == null || kbName.isBlank() ? "全部题库" : kbName)
                .replaceAll("[\\\\/:*?\"<>|]", "_");
        String stamp = LocalDate.now().toString();

        return switch (format == null ? "anki" : format.toLowerCase()) {
            case "json" -> new ExportFile(
                    safeName + "-题库-" + stamp + ".json",
                    "application/json",
                    toJson(questions, optionMap, tagMap).getBytes(StandardCharsets.UTF_8));
            case "csv" -> new ExportFile(
                    safeName + "-题库-" + stamp + ".csv",
                    "text/csv",
                    toCsv(questions, optionMap, tagMap).getBytes(StandardCharsets.UTF_8));
            default -> new ExportFile(
                    safeName + "-Anki-" + stamp + ".txt",
                    "text/plain",
                    toAnki(questions, optionMap, tagMap).getBytes(StandardCharsets.UTF_8));
        };
    }

    // ------------------------------------------------------------------
    //  Anki：正面 \t 背面 \t 标签
    // ------------------------------------------------------------------

    private String toAnki(List<Question> questions,
                          Map<Long, List<QuestionOption>> optionMap,
                          Map<Long, List<com.beibei.dto.DocDto.TagBrief>> tagMap) {
        StringBuilder sb = new StringBuilder();
        // Anki 的导入说明行，带上它用户不用手动选分隔符
        sb.append("#separator:tab\n#html:false\n#columns:Front\tBack\tTags\n");

        for (Question q : questions) {
            StringBuilder front = new StringBuilder(escapeAnki(q.getStem()));
            List<QuestionOption> options = optionMap.getOrDefault(q.getId(), List.of());
            if (!options.isEmpty()) {
                front.append("<br>");
                for (QuestionOption o : options) {
                    front.append("<br>").append(o.getOptionKey()).append(". ")
                            .append(escapeAnki(o.getContent()));
                }
            }
            if (q.getCodeSnippet() != null && !q.getCodeSnippet().isBlank()) {
                front.append("<br><br>").append(escapeAnki(q.getCodeSnippet()));
            }

            StringBuilder back = new StringBuilder("答案：").append(escapeAnki(q.getAnswer()));
            if (q.getRubric() != null && !q.getRubric().isBlank()) {
                back.append("<br><br>评分要点：<br>").append(escapeAnki(q.getRubric()));
            }
            if (q.getAnalysis() != null && !q.getAnalysis().isBlank()) {
                back.append("<br><br>解析：").append(escapeAnki(q.getAnalysis()));
            }

            List<String> tags = new ArrayList<>();
            tags.add(typeLabel(q.getQType()));
            tags.add(q.getDifficulty() != null && q.getDifficulty() == 1 ? "简单"
                    : q.getDifficulty() != null && q.getDifficulty() == 3 ? "困难" : "中等");
            for (com.beibei.dto.DocDto.TagBrief t : tagMap.getOrDefault(q.getId(), List.of())) {
                tags.add(t.name().replaceAll("[\\s,]", "_"));
            }

            sb.append(front).append('\t').append(back).append('\t')
                    .append(String.join(" ", tags)).append('\n');
        }
        return sb.toString();
    }

    /** Anki 的字段里不能出现真实制表符与换行 */
    private String escapeAnki(String text) {
        if (text == null) {
            return "";
        }
        return text.replace("\t", "    ")
                .replace("\r\n", "<br>")
                .replace("\n", "<br>")
                .trim();
    }

    // ------------------------------------------------------------------
    //  CSV
    // ------------------------------------------------------------------

    private String toCsv(List<Question> questions,
                         Map<Long, List<QuestionOption>> optionMap,
                         Map<Long, List<com.beibei.dto.DocDto.TagBrief>> tagMap) {
        StringBuilder sb = new StringBuilder();
        sb.append('\uFEFF');   // UTF-8 BOM，否则 Excel 打开中文乱码
        sb.append("ID,题型,难度,题干,选项,答案,评分要点,解析,知识点,状态\n");

        for (Question q : questions) {
            List<QuestionOption> options = optionMap.getOrDefault(q.getId(), List.of());
            String optionText = options.stream()
                    .map(o -> o.getOptionKey() + "." + o.getContent() + (isCorrect(o) ? "(√)" : ""))
                    .collect(Collectors.joining(" | "));
            String tags = tagMap.getOrDefault(q.getId(), List.of()).stream()
                    .map(com.beibei.dto.DocDto.TagBrief::name)
                    .collect(Collectors.joining("、"));

            sb.append(csv(q.getId())).append(',')
                    .append(csv(typeLabel(q.getQType()))).append(',')
                    .append(csv(QuestionDto.difficultyName(q.getDifficulty()))).append(',')
                    .append(csv(q.getStem())).append(',')
                    .append(csv(optionText)).append(',')
                    .append(csv(q.getAnswer())).append(',')
                    .append(csv(q.getRubric())).append(',')
                    .append(csv(q.getAnalysis())).append(',')
                    .append(csv(tags)).append(',')
                    .append(csv(q.getStatus() == null ? "" : q.getStatus() == 1 ? "已发布" : "待审"))
                    .append('\n');
        }
        return sb.toString();
    }

    private boolean isCorrect(QuestionOption o) {
        return o.getIsCorrect() != null && o.getIsCorrect() == 1;
    }

    private String csv(Object value) {
        if (value == null) {
            return "";
        }
        String text = String.valueOf(value).replace("\r\n", " ").replace("\n", " ").trim();
        if (text.contains(",") || text.contains("\"") || text.contains("\n")) {
            return "\"" + text.replace("\"", "\"\"") + "\"";
        }
        return text;
    }

    // ------------------------------------------------------------------
    //  JSON：全量字段，便于迁移
    // ------------------------------------------------------------------

    private String toJson(List<Question> questions,
                          Map<Long, List<QuestionOption>> optionMap,
                          Map<Long, List<com.beibei.dto.DocDto.TagBrief>> tagMap) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (Question q : questions) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", q.getId());
            row.put("kbId", q.getKbId());
            row.put("qType", q.getQType());
            row.put("qTypeName", typeLabel(q.getQType()));
            row.put("difficulty", q.getDifficulty());
            row.put("stem", q.getStem());
            row.put("answer", q.getAnswer());
            row.put("analysis", q.getAnalysis());
            row.put("codeSnippet", q.getCodeSnippet());
            row.put("rubric", parseJson(q.getRubric()));
            row.put("sourceChunkIds", parseJson(q.getSourceChunkIds()));
            row.put("status", q.getStatus());
            row.put("origin", q.getOrigin());
            row.put("options", optionMap.getOrDefault(q.getId(), List.of()).stream()
                    .map(o -> Map.of("key", o.getOptionKey(), "content", o.getContent(),
                            "correct", isCorrect(o)))
                    .toList());
            row.put("tags", tagMap.getOrDefault(q.getId(), List.of()).stream()
                    .map(com.beibei.dto.DocDto.TagBrief::name).toList());
            list.add(row);
        }

        Map<String, Object> root = new LinkedHashMap<>();
        root.put("exportedAt", java.time.LocalDateTime.now().toString());
        root.put("count", list.size());
        root.put("questions", list);
        try {
            return objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(root);
        } catch (Exception e) {
            return "{\"count\":0,\"questions\":[]}";
        }
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception e) {
            return json;
        }
    }
}
