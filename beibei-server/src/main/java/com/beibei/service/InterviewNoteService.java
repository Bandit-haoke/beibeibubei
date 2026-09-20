package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.BusinessException;
import com.beibei.dto.InterviewNoteDto;
import com.beibei.entity.AsyncTask;
import com.beibei.entity.InterviewNote;
import com.beibei.entity.InterviewNoteTurn;
import com.beibei.mapper.InterviewNoteMapper;
import com.beibei.mapper.InterviewNoteTurnMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 面经业务。
 *
 * <p>职责划分与其它模块一致：<b>Java 管数据与文件，Python 管 AI</b>。
 * 所以这里只做三件事 —— 收音频落盘、建库记录、建异步任务；
 * 转写、分角色、清洗、成文全在 beibei-agent，结果由 Python 直接写回
 * {@code bb_interview_note} 与 {@code bb_interview_note_turn}。
 *
 * <p>换句话说：即使 Java 重启，已经跑完的面经也不会丢，因为它早就在数据库里了。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InterviewNoteService {

    private final InterviewNoteMapper noteMapper;
    private final InterviewNoteTurnMapper turnMapper;
    private final FileStorageService storage;
    private final AsyncTaskService taskService;
    private final InterviewNoteRunner runner;
    private final ObjectMapper objectMapper;

    private static final TypeReference<List<InterviewNoteDto.QuestionVO>> QUESTION_LIST =
            new TypeReference<>() {
            };
    private static final TypeReference<List<String>> STRING_LIST = new TypeReference<>() {
    };

    // ------------------------------------------------------------------
    //  上传
    // ------------------------------------------------------------------

    public InterviewNoteDto.UploadResult upload(MultipartFile file, String company, String position) {
        FileStorageService.StoredFile stored = storage.storeAudio(file);

        InterviewNote note = new InterviewNote();
        note.setUserId(1L);
        note.setTitle("");
        note.setCompany(trim(company));
        note.setPosition(trim(position));
        note.setFileName(stored.originalName());
        note.setFilePath(stored.relativePath());
        note.setFileSize(stored.size());
        note.setFileType(stored.ext());
        note.setDurationMs(0);
        note.setEngine("");
        note.setRoleSource("");
        note.setStatus(InterviewNote.STATUS_PENDING);
        note.setProgress(0);
        note.setStage("排队中");
        note.setTurnCount(0);
        note.setQuestionCount(0);
        note.setSpeakerCount(0);
        note.setSummary("");
        note.setErrorMsg("");
        noteMapper.insert(note);

        Long taskId = startGenerate(note);
        log.info("面经录音已上传 #{} {} -> {}", note.getId(), stored.originalName(), stored.relativePath());
        return new InterviewNoteDto.UploadResult(note.getId(), taskId, stored.originalName(),
                "已加入转写队列，录音越长处理越久，可以先去做别的");
    }

    /** 失败后重来一次（音频还在，不用重传）。 */
    public Long retry(Long id) {
        InterviewNote note = require(id);
        if (note.getFilePath() == null || note.getFilePath().isBlank()) {
            throw BusinessException.invalid("这条面经没有关联音频文件，无法重试，请重新上传");
        }
        InterviewNote patch = new InterviewNote();
        patch.setId(id);
        patch.setStatus(InterviewNote.STATUS_PENDING);
        patch.setProgress(0);
        patch.setStage("排队中");
        patch.setErrorMsg("");
        noteMapper.updateById(patch);
        return startGenerate(note);
    }

    private Long startGenerate(InterviewNote note) {
        AsyncTask task = taskService.create(AsyncTask.TYPE_INTERVIEW_NOTE, note.getId(), 1L);
        runner.runGenerate(task.getId(), note.getId(), note.getFilePath(), note.getFileName(),
                note.getCompany(), note.getPosition());
        return task.getId();
    }

    // ------------------------------------------------------------------
    //  查询
    // ------------------------------------------------------------------

    public List<InterviewNoteDto.NoteVO> list() {
        List<InterviewNote> list = noteMapper.selectList(
                Wrappers.<InterviewNote>lambdaQuery().orderByDesc(InterviewNote::getCreatedAt));
        return list.stream().map(this::toVO).toList();
    }

    public InterviewNoteDto.DetailVO detail(Long id) {
        InterviewNote note = require(id);
        List<InterviewNoteTurn> turns = turnMapper.selectList(
                Wrappers.<InterviewNoteTurn>lambdaQuery()
                        .eq(InterviewNoteTurn::getNoteId, id)
                        .orderByAsc(InterviewNoteTurn::getSeq));

        List<InterviewNoteDto.TurnVO> turnVOs = turns.stream()
                .map(t -> new InterviewNoteDto.TurnVO(
                        t.getSeq(),
                        t.getRole(),
                        t.getStartMs(),
                        t.getEndMs(),
                        // 前端优先展示清洗后的文本；清洗后为空则退回原文，避免出现空行
                        (t.getCleanText() == null || t.getCleanText().isBlank())
                                ? t.getRawText() : t.getCleanText(),
                        t.getRawText(),
                        t.getRemovedWords(),
                        t.getQuestionType()))
                .toList();

        return new InterviewNoteDto.DetailVO(
                toVO(note),
                turnVOs,
                readQuestions(note.getQuestionsJson()),
                readStrings(note.getHighlightsJson()),
                note.getContent() == null ? "" : note.getContent());
    }

    // ------------------------------------------------------------------
    //  修改 / 删除
    // ------------------------------------------------------------------

    public InterviewNoteDto.NoteVO update(Long id, InterviewNoteDto.UpdateReq req) {
        require(id);
        InterviewNote patch = new InterviewNote();
        patch.setId(id);
        if (req.title() != null) {
            patch.setTitle(req.title().trim());
        }
        if (req.company() != null) {
            patch.setCompany(req.company().trim());
        }
        if (req.position() != null) {
            patch.setPosition(req.position().trim());
        }
        noteMapper.updateById(patch);
        return toVO(require(id));
    }

    public void delete(Long id) {
        InterviewNote note = require(id);
        turnMapper.delete(Wrappers.<InterviewNoteTurn>lambdaQuery()
                .eq(InterviewNoteTurn::getNoteId, id));
        noteMapper.deleteById(id);
        // 音频文件一并删掉，否则 D:/beibei-data/upload/audio 会越堆越大
        storage.delete(note.getFilePath());
        log.info("面经 #{} 已删除（含音频文件）", id);
    }

    // ------------------------------------------------------------------
    //  内部
    // ------------------------------------------------------------------

    private InterviewNote require(Long id) {
        InterviewNote note = id == null ? null : noteMapper.selectById(id);
        if (note == null) {
            throw BusinessException.notFound("面经", id);
        }
        return note;
    }

    private InterviewNoteDto.NoteVO toVO(InterviewNote n) {
        return new InterviewNoteDto.NoteVO(
                n.getId(), n.getTitle(), n.getCompany(), n.getPosition(),
                n.getFileName(), n.getFileType(), n.getFileSize(), n.getDurationMs(),
                n.getEngine(), n.getRoleSource(), n.getStatus(), n.getProgress(), n.getStage(),
                n.getTurnCount(), n.getQuestionCount(), n.getSpeakerCount(),
                n.getSummary(), n.getErrorMsg(), n.getCreatedAt());
    }

    private List<InterviewNoteDto.QuestionVO> readQuestions(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            List<InterviewNoteDto.QuestionVO> raw = objectMapper.readValue(json, QUESTION_LIST);
            // AI 偶尔会漏字段，统一补空串，前端就不用到处判 null
            return raw.stream()
                    .map(q -> new InterviewNoteDto.QuestionVO(
                            q.question() == null ? "" : q.question(),
                            q.answer() == null ? "" : q.answer(),
                            q.category() == null ? "" : q.category()))
                    .toList();
        } catch (Exception e) {
            log.warn("解析面经问题清单失败: {}", e.getMessage());
            return List.of();
        }
    }

    private List<String> readStrings(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, STRING_LIST);
        } catch (Exception e) {
            log.warn("解析面经经验点失败: {}", e.getMessage());
            return List.of();
        }
    }

    private static String trim(String value) {
        return value == null ? "" : value.trim();
    }
}
