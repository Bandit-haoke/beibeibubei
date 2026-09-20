package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 面经：用户上传的<b>真实</b>面试录音，经转写、分角色、清洗后由 AI 整理的成文记录。表 bb_interview_note。
 *
 * <p>与 {@link Interview} 的区别（很容易混）：
 * <ul>
 *   <li>{@code bb_interview} —— 本工具<b>扮演</b>面试官与用户对话，内容由 AI 生成；</li>
 *   <li>{@code bb_interview_note} —— 用户上传<b>已经发生过</b>的面试录音，AI 只做整理。</li>
 * </ul>
 * 两者互不依赖。
 *
 * <p>逐句对话在 {@link InterviewNoteTurn}，这张表只放元信息与最终成品。
 */
@Data
@TableName("bb_interview_note")
public class InterviewNote implements Serializable {

    /** 已上传，等待处理 */
    public static final int STATUS_PENDING = 0;
    /** 正在转写 */
    public static final int STATUS_TRANSCRIBING = 1;
    /** 转写完成，正在判定角色/清洗 */
    public static final int STATUS_TRANSCRIBED = 2;
    /** 正在生成面经正文 */
    public static final int STATUS_SUMMARIZING = 3;
    /** 完成 */
    public static final int STATUS_DONE = 4;
    /** 失败 */
    public static final int STATUS_FAILED = 9;

    /** 转写引擎：讯飞语音转写，带原生角色分离 */
    public static final String ENGINE_LFASR = "LFASR";
    /** 转写引擎：讯飞语音听写（降级路径，无角色分离） */
    public static final String ENGINE_IAT = "IAT";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    /** 面经标题，AI 生成后可人工修改 */
    private String title;

    private String company;

    private String position;

    private String fileName;

    /** 相对上传目录的路径，形如 audio/202609/xxxx.mp3 */
    private String filePath;

    private Long fileSize;

    /** mp3/wav/m4a/flac/opus */
    private String fileType;

    private Integer durationMs;

    /** LFASR 或 IAT */
    private String engine;

    /** LFASR=引擎原生角色分离；LLM=大模型推断 */
    private String roleSource;

    private Integer status;

    private Integer progress;

    private String stage;

    /** 清洗后保留的句子数 */
    private Integer turnCount;

    /** 面试官提问数 */
    private Integer questionCount;

    /** 引擎识别出的说话人个数（降级路径恒为 0） */
    private Integer speakerCount;

    private String summary;

    /** 面经正文（Markdown） */
    private String content;

    /** 结构化问题清单：[{question, answer, category}] */
    private String questionsJson;

    /** 经验点数组 */
    private String highlightsJson;

    /** 转写原文（含说话人编号与时间戳），用于人工核对 AI 整理得对不对 */
    private String rawJson;

    private String errorMsg;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
