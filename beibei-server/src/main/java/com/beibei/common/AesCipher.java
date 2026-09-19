package com.beibei.common;

import lombok.extern.slf4j.Slf4j;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * API Key 的对称加密（AES-256-GCM）。
 *
 * <p>密钥由配置里的明文口令经 SHA-256 派生。**Python 侧用同一口令做同样的运算**
 * （见 beibei-agent/app/core/crypto.py），所以两边能互相解开 ——
 * Java 存进去的 Key，Python 调用模型时要能读出来。
 *
 * <p>密文格式：Base64( 12 字节 IV ‖ 密文 ‖ 16 字节 GCM tag )。
 * 这是 AESGCM 的标准布局，Python 的 cryptography 库产出的字节完全一致。
 *
 * <p>解密失败一律返回原值 —— 兼容早期直接存的明文，也避免密钥换了之后整个服务起不来。
 */
@Slf4j
public final class AesCipher {

    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final int IV_LENGTH = 12;
    private static final int TAG_BITS = 128;

    private static volatile SecretKeySpec keySpec;
    private static volatile String currentSecret;
    private static final SecureRandom RANDOM = new SecureRandom();

    private AesCipher() {
    }

    private static SecretKeySpec key(String secret) {
        if (keySpec != null && secret.equals(currentSecret)) {
            return keySpec;
        }
        synchronized (AesCipher.class) {
            if (keySpec == null || !secret.equals(currentSecret)) {
                try {
                    byte[] digest = MessageDigest.getInstance("SHA-256")
                            .digest(secret.getBytes(StandardCharsets.UTF_8));
                    keySpec = new SecretKeySpec(digest, "AES");
                    currentSecret = secret;
                } catch (Exception e) {
                    throw new IllegalStateException("无法派生加密密钥", e);
                }
            }
            return keySpec;
        }
    }

    public static String encrypt(String plain, String secret) {
        if (plain == null || plain.isEmpty()) {
            return "";
        }
        try {
            byte[] iv = new byte[IV_LENGTH];
            RANDOM.nextBytes(iv);
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, key(secret), new GCMParameterSpec(TAG_BITS, iv));
            byte[] cipherText = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));

            byte[] out = new byte[iv.length + cipherText.length];
            System.arraycopy(iv, 0, out, 0, iv.length);
            System.arraycopy(cipherText, 0, out, iv.length, cipherText.length);
            return Base64.getEncoder().encodeToString(out);
        } catch (Exception e) {
            // 加密失败宁可存明文也不要丢配置
            log.warn("加密失败，按明文存储：{}", e.getMessage());
            return plain;
        }
    }

    public static String decrypt(String stored, String secret) {
        if (stored == null || stored.isEmpty()) {
            return "";
        }
        try {
            byte[] raw = Base64.getDecoder().decode(stored);
            if (raw.length <= IV_LENGTH) {
                return stored;
            }
            byte[] iv = new byte[IV_LENGTH];
            System.arraycopy(raw, 0, iv, 0, IV_LENGTH);
            byte[] cipherText = new byte[raw.length - IV_LENGTH];
            System.arraycopy(raw, IV_LENGTH, cipherText, 0, cipherText.length);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, key(secret), new GCMParameterSpec(TAG_BITS, iv));
            return new String(cipher.doFinal(cipherText), StandardCharsets.UTF_8);
        } catch (Exception e) {
            // 不是密文（早期明文 / 换了密钥）就原样返回
            return stored;
        }
    }

    /** 脱敏展示：sk-abcdef…wxyz */
    public static String mask(String value) {
        if (value == null || value.isEmpty()) {
            return "";
        }
        if (value.length() <= 10) {
            return "****";
        }
        return value.substring(0, 6) + "****" + value.substring(value.length() - 4);
    }
}
