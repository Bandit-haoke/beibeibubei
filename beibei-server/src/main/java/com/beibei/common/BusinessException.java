package com.beibei.common;

/**
 * 业务异常。抛出后由 {@link GlobalExceptionHandler} 统一转成 Result。
 */
public class BusinessException extends RuntimeException {

    private final int code;

    public BusinessException(String message) {
        this(Result.BAD_REQUEST, message);
    }

    public BusinessException(int code, String message) {
        super(message);
        this.code = code;
    }

    public int getCode() {
        return code;
    }

    public static BusinessException notFound(String what, Object id) {
        return new BusinessException(Result.BAD_REQUEST, what + " 不存在：" + id);
    }

    public static BusinessException invalid(String message) {
        return new BusinessException(Result.BAD_REQUEST, message);
    }
}
