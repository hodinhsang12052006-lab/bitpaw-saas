import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Lưu trữ JWT an toàn — Keychain (iOS) / Keystore-backed EncryptedSharedPreferences (Android).
/// KHÔNG dùng shared_preferences: token là bằng chứng đăng nhập trọn vẹn (Bearer token thay thế
/// hoàn toàn session cookie), lưu plaintext trên máy đã root/jailbreak = mất tài khoản ngay.
class StorageService {
  static const _tokenKey = 'bitpaw_jwt_access_token';

  final FlutterSecureStorage _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  Future<void> saveToken(String token) async {
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<String?> getToken() async {
    return _storage.read(key: _tokenKey);
  }

  Future<void> deleteToken() async {
    await _storage.delete(key: _tokenKey);
  }

  Future<bool> hasToken() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }
}
