package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.BusinessException;
import com.beibei.dto.InterviewDto;
import com.beibei.dto.PaperDto;
import com.beibei.entity.AsyncTask;
import com.beibei.entity.Interview;
import com.beibei.entity.InterviewTurn;
import com.beibei.entity.KnowledgeBase;
import com.beibei.entity.Resume;
import com.beibei.entity.Tag;
import com.beibei.mapper.InterviewMapper;
import com.beibei.mapper.InterviewTurnMapper;
import com.beibei.mapper.ResumeMapper;
import com.beibei.mapper.TagMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * AI 模拟面试业务。
 *
 * <p>模块边界（重要）：简历库与学习知识库**完全隔离**。
 * 简历不进 Milvus、不建知识点树、不参与 RAG 检索。
 * 唯一的跨界通道是 {@link #createLinkagePaper} —— 把面试报告里的薄弱知识点，
 * 拿去关联知识库里按名字匹配知识点，再走现成的出题流水线。
 *
 * <p>职责分工同样是「Java 管数据、Python 管 AI」：
 * 对话轮次、状态机、报告落库都在 Java；提问/评分/出报告都是调一次 Python。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InterviewService {

    /** 简历不属于任何知识库，落盘时用 0 当目录名（见 FileStorageService 的目录规则） */
    private static final long RESUME_DIR = 0L;

    private static final DateTimeFormatter TITLE_TIME = DateTimeFormatter.ofPattern("MM-dd HH:mm");

    private static final int DEFAULT_MAX_TURNS = 10;

    private final ResumeMapper resumeMapper;
    private final InterviewMapper interviewMapper;
    private final InterviewTurnMapper turnMapper;
    private final TagMapper tagMapper;
    private final FileStorageService storage;
    private final AsyncTaskService taskService;
    private final InterviewRunner interviewRunner;
    private final AgentClient agentClient;
    private final KnowledgeBaseService kbService;
    private final PaperService paperService;
    private final ObjectMapper objectMapper;

    // ==================================================================
    //  一、简历库
    // ==================================================================

    public InterviewDto.ResumeUploadResult uploadResume(MultipartFile file) {
        FileStorageService.StoredFile stored = storage.store(RESUME_DIR, file);

        Resume resume = new Resume();
        resume.setUserId(1L);
        resume.setFileName(stored.originalName());
        resume.setFilePath(stored.relativePath());
        resume.setFileSize(stored.size());
        resume.setFileType(stored.ext());
        resume.setCharCount(0);
        resume.setTargetPosition("");
        resume.setStatus(Resume.STATUS_PENDING);
        resume.setErrorMsg("");
        resumeMapper.insert(resume);

        Long taskId = startParse(resume, null);
        log.info("简历已上传 #{} {} -> {}", resume.getId(), stored.originalName(), stored.relativePath());
        return new InterviewDto.ResumeUploadResult(resume.getId(), taskId,
                stored.originalName(), false, "已加入解析队列");
    }

    /** 手动粘贴简历文字（没有文件也能面试）。 */
    public InterviewDto.ResumeUploadResult pasteResume(InterviewDto.ResumePasteReq req) {
        if (req == null || req.content() == null || req.content().isBlank()) {
            throw BusinessException.invalid("粘贴内容不能为空");
        }
        String name = (req.fileName() == null || req.fileName().isBlank())
                ? "手动录入简历.txt" : req.fileName().trim();

        Resume resume = new Resume();
        resume.setUserId(1L);
        resume.setFileName(name);
        resume.setFilePath("");
        resume.setFileSize((long) req.content().getBytes(java.nio.charset.StandardCharsets.UTF_8).length);
        resume.setFileType("txt");
        resume.setCharCount(0);
        resume.setTargetPosition(req.targetPosition() == null ? "" : req.targetPosition().trim());
        resume.setStatus(Resume.STATUS_PENDING);
        resume.setErrorMsg("");
        resumeMapper.insert(resume);

        Long taskId = startParse(resume, req.content());
        return new InterviewDto.ResumeUploadResult(resume.getId(), taskId, name, false, "已加入解析队列");
    }

    /** 重新解析（换了模型、或上次 OCR 失败时用）。 */
    public Long reparseResume(Long id) {
        Resume resume = requireResume(id);
        Resume patch = new Resume();
        patch.setId(id);
        patch.setStatus(Resume.STATUS_PENDING);
        patch.setErrorMsg("");
        resumeMapper.updateById(patch);

        // 粘贴型简历没有文件，直接把原文回喂给 Python
        String textContent = (resume.getFilePath() == null || resume.getFilePath().isBlank())
                ? resume.getRawText() : null;
        return startParse(resume, textContent);
    }

    private Long startParse(Resume resume, String textContent) {
        AsyncTask task = taskService.create(AsyncTask.TYPE_RESUME_PARSE, resume.getId(), 1L);
        interviewRunner.runParse(task.getId(), resume.getId(), textContent);
        return task.getId();
    }

    public List<InterviewDto.ResumeVO> listResumes() {
        List<Resume> list = resumeMapper.selectList(
                Wrappers.<Resume>lambdaQuery().orderByDesc(Resume::getCreatedAt));
        return list.stream().map(this::toResumeVO).toList();
    }

    public InterviewDto.ResumeDetailVO resumeDetail(Long id) {
        Resume resume = requireResume(id);
        return new InterviewDto.ResumeDetailVO(toResumeVO(resume), parseMap(resume.getProfileJson()),
                resume.getRawText() == null ? "" : resume.getRawText());
    }

    public void deleteResume(Long id) {
        Resume resume = requireResume(id);
        List<Interview> interviews = interviewMapper.selectList(
                Wrappers.<Interview>lambdaQuery().eq(Interview::getResumeId, id));
        for (Interview interview : interviews) {
            deleteInterview(interview.getId());
        }
        if (resume.getFilePath() != null && !resume.getFilePath().isBlank()) {
            storage.delete(resume.getFilePath());
        }
        resumeMapper.deleteById(id);
        log.info("已删除简历 #{}（连带 {} 场面试）", id, interviews.size());
    }

    private InterviewDto.ResumeVO toResumeVO(Resume r) {
        Map<String, Object> profile = parseMap(r.getProfileJson());
        return new InterviewDto.ResumeVO(
                r.getId(), r.getFileName(), r.getFileType(), r.getFileSize(), r.getCharCount(),
                r.getTargetPosition(), r.getStatus(), r.getErrorMsg(),
                sizeOf(profile.get("skills")), sizeOf(profile.get("projects")), sizeOf(profile.get("risks")),
                r.getCreatedAt(), r.getUpdatedAt());
    }

    // ==================================================================
    //  二、面试
    // ==================================================================

    public InterviewDto.StartVO startInterview(InterviewDto.StartReq req) {
        Resume resume = requireResume(req.resumeId());
        if (resume.getStatus() == null || resume.getStatus() != Resume.STATUS_READY) {
            throw BusinessException.invalid("这份简历还没解析成功，请先等解析完成或点「重新解析」");
        }
        if (req.kbId() != null) {
            kbService.require(req.kbId());   // 关联知识库必须存在，早点报错
        }

        String jobTitle = (req.jobTitle() == null || req.jobTitle().isBlank())
                ? (resume.getTargetPosition() == null || resume.getTargetPosition().isBlank()
                   ? "Java 后端开发工程师" : resume.getTargetPosition())
                : req.jobTitle().trim();

        int difficulty = req.difficulty() == null ? Interview.DIFFICULTY_MIDDLE : req.difficulty();
        int maxTurns = req.maxTurns() == null ? DEFAULT_MAX_TURNS : req.maxTurns();

        Interview interview = new Interview();
        interview.setUserId(1L);
        interview.setResumeId(req.resumeId());
        interview.setKbId(req.kbId());
        interview.setJobTitle(jobTitle);
        interview.setDifficulty(difficulty);
        interview.setMaxTurns(maxTurns);
        interview.setTurnCount(0);
        interview.setStatus(Interview.STATUS_DRAFT);
        interview.setSummary("");
        interviewMapper.insert(interview);

        Map<String, Object> body = agentClient.interviewStart(interview.getId());
        requireOk(body, "开始面试失败");
        Map<String, Object> question = asMap(body.get("question"));

        return new InterviewDto.StartVO(
                interview.getId(), jobTitle, difficulty, maxTurns, 0, toQuestionVO(question));
    }

    public InterviewDto.AnswerVO answer(Long interviewId, InterviewDto.AnswerReq req) {
        requireInterview(interviewId);
        String answer = req == null || req.answer() == null ? "" : req.answer().trim();
        if (answer.isEmpty()) {
            throw BusinessException.invalid("请先说出或输入你的回答");
        }

        Map<String, Object> body = agentClient.interviewAnswer(interviewId, answer);
        requireOk(body, "评分失败");

        Map<String, Object> next = asMap(body.get("nextQuestion"));
        return new InterviewDto.AnswerVO(
                interviewId,
                asInt(body.get("turnCount")),
                asInt(body.get("maxTurns")),
                Boolean.TRUE.equals(body.get("finished")),
                asMap(body.get("evaluation")),
                next.isEmpty() ? null : toQuestionVO(next));
    }

    /** 生成报告（可在轮数用完后手动触发，也可中途提前结束）。 */
    public InterviewDto.DetailVO finish(Long interviewId) {
        requireInterview(interviewId);
        Map<String, Object> body = agentClient.interviewFinish(interviewId);
        requireOk(body, "生成面试报告失败");
        return detail(interviewId);
    }

    public List<InterviewDto.InterviewVO> listInterviews() {
        List<Interview> list = interviewMapper.selectList(
                Wrappers.<Interview>lambdaQuery().orderByDesc(Interview::getCreatedAt));
        if (list.isEmpty()) {
            return List.of();
        }
        Map<Long, Resume> resumes = resumesById(list.stream().map(Interview::getResumeId).toList());
        Map<Long, String> kbNames = kbNamesById(list.stream().map(Interview::getKbId).toList());
        return list.stream().map(i -> toInterviewVO(i, resumes, kbNames)).toList();
    }

    public InterviewDto.DetailVO detail(Long interviewId) {
        Interview interview = requireInterview(interviewId);
        Map<Long, Resume> resumes = resumesById(List.of(interview.getResumeId()));
        Map<Long, String> kbNames = kbNamesById(java.util.Collections.singletonList(interview.getKbId()));

        List<InterviewTurn> turns = turnMapper.selectList(
                Wrappers.<InterviewTurn>lambdaQuery()
                        .eq(InterviewTurn::getInterviewId, interviewId)
                        .orderByAsc(InterviewTurn::getSeq)
                        .orderByAsc(InterviewTurn::getId));

        List<InterviewDto.TurnVO> turnVOs = turns.stream().map(t -> new InterviewDto.TurnVO(
                t.getId(), t.getSeq(), t.getRole(), t.getContent(), t.getQuestionType(),
                t.getBasedOn(), parseStringList(t.getExpects()), t.getScore(),
                parseMap(t.getFeedbackJson()), t.getCreatedAt())).toList();

        return new InterviewDto.DetailVO(
                toInterviewVO(interview, resumes, kbNames), turnVOs,
                parseMap(interview.getReportJson()));
    }

    public void deleteInterview(Long interviewId) {
        requireInterview(interviewId);
        turnMapper.delete(Wrappers.<InterviewTurn>lambdaQuery()
                .eq(InterviewTurn::getInterviewId, interviewId));
        interviewMapper.deleteById(interviewId);
        log.info("已删除面试 #{}", interviewId);
    }

    // ==================================================================
    //  三、与学习模块的联动：薄弱知识点 → 专项题卷
    // ==================================================================

    /**
     * 拿面试报告里的薄弱知识点去关联知识库匹配知识点，然后走现成的出题流水线。
     *
     * <p>匹配策略是**双向包含**：报告说「Redis 缓存穿透」，知识库里有「缓存穿透」，
     * 也算命中。因为大模型给的知识点名和人工建的标签名，粒度天然对不齐。
     * 一个都没匹配上时不报错，退化成「整库出题」，并在返回里说明原因。
     */
    public InterviewDto.LinkageVO createLinkagePaper(Long interviewId, InterviewDto.LinkageReq req) {
        Interview interview = requireInterview(interviewId);
        if (interview.getStatus() == null || interview.getStatus() != Interview.STATUS_FINISHED) {
            throw BusinessException.invalid("面试还没结束，先生成评估报告再来出题");
        }

        Long kbId = req != null && req.kbId() != null ? req.kbId() : interview.getKbId();
        if (kbId == null) {
            throw BusinessException.invalid("这场面试没有关联知识库，请先选择要出题的知识库");
        }
        KnowledgeBase kb = kbService.require(kbId);

        Map<String, Object> report = parseMap(interview.getReportJson());
        List<String> points = toStringList(report.get("knowledgePoints"));
        if (points.isEmpty()) {
            List<Map<String, Object>> weak = asMapList(report.get("weakPoints"));
            points = weak.stream().map(w -> String.valueOf(w.getOrDefault("skill", "")))
                    .filter(s -> !s.isBlank()).toList();
        }

        List<Long> tagIds = new ArrayList<>();
        List<String> matched = new ArrayList<>();
        List<String> unmatched = new ArrayList<>();
        List<InterviewDto.MatchVO> matches = new ArrayList<>();

        if (req != null && req.tagIds() != null && !req.tagIds().isEmpty()) {
            tagIds.addAll(req.tagIds());
            for (Tag tag : tagMapper.selectBatchIds(req.tagIds())) {
                matched.add(tag.getName());
                matches.add(new InterviewDto.MatchVO("（手动指定）", tag.getName(),
                        tag.getId(), tag.getChunkCount()));
            }
        } else if (!points.isEmpty()) {
            List<Tag> tags = candidateTags(kbId);
            for (String point : points) {
                Tag hit = bestMatch(point, tags);
                if (hit == null) {
                    unmatched.add(point);
                } else if (!tagIds.contains(hit.getId())) {
                    tagIds.add(hit.getId());
                    matched.add(hit.getName());
                    matches.add(new InterviewDto.MatchVO(point, hit.getName(),
                            hit.getId(), hit.getChunkCount()));
                }
            }
        }

        int count = req != null && req.count() != null ? req.count()
                : Math.max(5, Math.min(30, Math.max(1, matched.size()) * 3));
        String title = "面试薄弱点专项 · " + interview.getJobTitle()
                + " · " + LocalDateTime.now().format(TITLE_TIME);

        PaperDto.GenerateReq generateReq = new PaperDto.GenerateReq(
                kbId, title, count, tagIds.isEmpty() ? null : tagIds, true,
                null, null,
                req == null || req.selfCheck() == null || req.selfCheck(),
                req == null ? null : req.providerId());

        PaperDto.GenerateResult result = paperService.generate(generateReq);

        String message;
        if (tagIds.isEmpty()) {
            message = "报告里的知识点在「" + kb.getName() + "」里没匹配到标签，已退化成整库出题";
        } else if (!unmatched.isEmpty()) {
            message = "已命中 " + matched.size() + " 个知识点；"
                    + unmatched.size() + " 个没匹配上，已忽略";
        } else {
            message = "已按 " + matched.size() + " 个薄弱知识点定向出题";
        }

        log.info("面试 #{} 联动出题：kb=#{} tags={} count={} paper=#{}",
                interviewId, kbId, tagIds, count, result.paperId());
        return new InterviewDto.LinkageVO(result.paperId(), result.taskId(), kbId, kb.getName(),
                matched, unmatched, matches, count, message);
    }

    /**
     * 挑出用来匹配的候选标签。
     *
     * <p>**优先只用有内容的标签**（chunk_count &gt; 0）。
     * 一个零分块的标签意味着它底下没有任何原文，出题时一块材料都取不到 ——
     * 匹配上它等于白匹配，还会把用户引到一个出不了题的「知识点」上。
     *
     * <p>但如果整个知识库的标签分块数都没统计过（全为 0），就不能这么筛，
     * 否则一个都匹配不到；这时退回用全部标签。
     */
    private List<Tag> candidateTags(Long kbId) {
        List<Tag> all = tagMapper.selectList(Wrappers.<Tag>lambdaQuery().eq(Tag::getKbId, kbId));
        if (all.isEmpty()) {
            return all;
        }
        List<Tag> withChunks = all.stream()
                .filter(t -> t.getChunkCount() != null && t.getChunkCount() > 0)
                .toList();
        if (!withChunks.isEmpty()) {
            log.debug("联动匹配只用有内容的知识点：{} / {} 个", withChunks.size(), all.size());
            return withChunks;
        }
        return all;
    }

    /**
     * 在候选标签里挑一个最贴合的。
     * 优先级：完全相同 > 标签名包含知识点 > 知识点包含标签名；同档取名字最长的（更具体）。
     */
    private Tag bestMatch(String point, List<Tag> tags) {
        String p = normalize(point);
        if (p.isEmpty()) {
            return null;
        }
        Tag exact = null;
        Tag nameContains = null;
        Tag pointContains = null;
        for (Tag tag : tags) {
            String name = normalize(tag.getName());
            if (name.isEmpty()) {
                continue;
            }
            if (name.equals(p)) {
                if (exact == null) {
                    exact = tag;
                }
            } else if (name.contains(p)) {
                if (nameContains == null
                        || name.length() > normalize(nameContains.getName()).length()) {
                    nameContains = tag;
                }
            } else if (p.contains(name)) {
                if (pointContains == null
                        || name.length() > normalize(pointContains.getName()).length()) {
                    pointContains = tag;
                }
            }
        }
        if (exact != null) {
            return exact;
        }
        return nameContains != null ? nameContains : pointContains;
    }

    /**
     * 归一化：小写、去空格与常见标点，并**剥掉 AI 生成标签常见的层级后缀**。
     *
     * <p>最后那步很关键：真实模型抽出来的知识点是「布隆过滤器原理与误判率」，
     * 而知识库里的标签往往叫「布隆过滤器」或者带层级后缀的「MySQL篇」。
     * 不剥后缀的话「MySQL」这个词永远匹配不上「MySQL篇」，
     * 实测就是这样导致 6 个薄弱知识点一个都没命中、闭环退化成整库出题。
     */
    private static String normalize(String text) {
        if (text == null) {
            return "";
        }
        String cleaned = text.toLowerCase(Locale.ROOT)
                .replaceAll("[\\s　（）()【】\\[\\]·、,，.。/\\\\\\-—:：;；'\"“”]", "");
        // 只剥结尾的层级词，不动中间的（"Redis 持久化" 不能变成 "Redis"）
        return cleaned.replaceAll("(篇|章|节|模块|部分|专题|系列|基础|入门|详解)$", "");
    }

    // ==================================================================
    //  内部工具
    // ==================================================================

    public Resume requireResume(Long id) {
        Resume resume = id == null ? null : resumeMapper.selectById(id);
        if (resume == null) {
            throw BusinessException.notFound("简历", id);
        }
        return resume;
    }

    public Interview requireInterview(Long id) {
        Interview interview = id == null ? null : interviewMapper.selectById(id);
        if (interview == null) {
            throw BusinessException.notFound("面试场次", id);
        }
        return interview;
    }

    private Map<Long, Resume> resumesById(List<Long> ids) {
        Set<Long> distinct = new LinkedHashSet<>(ids);
        distinct.remove(null);
        if (distinct.isEmpty()) {
            return Map.of();
        }
        return resumeMapper.selectBatchIds(distinct).stream()
                .collect(Collectors.toMap(Resume::getId, Function.identity(), (a, b) -> a));
    }

    private Map<Long, String> kbNamesById(List<Long> ids) {
        Set<Long> distinct = new LinkedHashSet<>(ids);
        distinct.remove(null);
        if (distinct.isEmpty()) {
            return Map.of();
        }
        Map<Long, String> names = new HashMap<>();
        for (Long id : distinct) {
            try {
                names.put(id, kbService.require(id).getName());
            } catch (Exception e) {
                names.put(id, "已删除的知识库 #" + id);
            }
        }
        return names;
    }

    private InterviewDto.InterviewVO toInterviewVO(Interview i, Map<Long, Resume> resumes,
                                                   Map<Long, String> kbNames) {
        Resume resume = resumes.get(i.getResumeId());
        String resumeName = resume == null ? "已删除的简历 #" + i.getResumeId() : resume.getFileName();
        return new InterviewDto.InterviewVO(
                i.getId(), i.getResumeId(), resumeName, i.getKbId(),
                i.getKbId() == null ? "" : kbNames.getOrDefault(i.getKbId(), ""),
                i.getJobTitle(), i.getDifficulty(), i.getMaxTurns(), i.getTurnCount(),
                i.getStatus(), i.getTotalScore(), i.getSummary(),
                i.getCreatedAt(), i.getStartedAt(), i.getFinishedAt());
    }

    private InterviewDto.QuestionVO toQuestionVO(Map<String, Object> question) {
        if (question == null || question.isEmpty()) {
            return null;
        }
        return new InterviewDto.QuestionVO(
                String.valueOf(question.getOrDefault("question", "")),
                String.valueOf(question.getOrDefault("type", "")),
                String.valueOf(question.getOrDefault("basedOn", "")),
                toStringList(question.get("expects")),
                asInt(question.get("turnNo")));
    }

    private void requireOk(Map<String, Object> body, String what) {
        if (body == null || body.isEmpty()) {
            throw new BusinessException(what + "：智能体返回空响应");
        }
        if (Boolean.FALSE.equals(body.get("ok"))) {
            Object error = body.get("error");
            String hint = body.get("hint") == null ? "" : "（" + body.get("hint") + "）";
            throw new BusinessException(what + "：" + (error == null ? "未知错误" : error) + hint);
        }
    }

    private static int sizeOf(Object value) {
        if (value instanceof List<?> list) {
            return list.size();
        }
        if (value instanceof Map<?, ?> map) {
            return map.size();
        }
        return 0;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> asMapList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        return list.stream().filter(Map.class::isInstance)
                .map(item -> (Map<String, Object>) item).toList();
    }

    private static int asInt(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    private Map<String, Object> parseMap(String json) {
        if (json == null || json.isBlank()) {
            return Map.of();
        }
        try {
            Map<String, Object> map = objectMapper.readValue(
                    json, new TypeReference<Map<String, Object>>() {
                    });
            return map == null ? Map.of() : map;
        } catch (Exception e) {
            log.warn("JSON 解析失败（忽略）：{}", e.getMessage());
            return Map.of();
        }
    }

    private List<String> parseStringList(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<String>>() {
            });
        } catch (Exception e) {
            return List.of();
        }
    }

    private static List<String> toStringList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        return list.stream().map(String::valueOf).filter(s -> !s.isBlank()).toList();
    }
}
