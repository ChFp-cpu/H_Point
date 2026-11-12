import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api.dart';
import 'session.dart';

enum _AuthStep { login, register, verify, resetEmail, resetCode }

class AuthPage extends StatefulWidget {
  const AuthPage({super.key, required this.session, this.register = false});

  final HPointSession session;
  final bool register;

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirmation = TextEditingController();
  final _code = TextEditingController();
  late _AuthStep _step = widget.register ? _AuthStep.register : _AuthStep.login;
  bool _busy = false;
  bool _obscure = true;
  String? _error;
  String? _notice;

  @override
  void dispose() {
    for (final controller in [_name, _email, _password, _confirmation, _code]) {
      controller.dispose();
    }
    super.dispose();
  }

  void _switchTo(_AuthStep step, {String? notice}) {
    setState(() {
      _step = step;
      _error = null;
      _notice = notice;
      _password.clear();
      _confirmation.clear();
      _code.clear();
    });
  }

  Future<void> _action(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await action();
    } catch (error) {
      if (!mounted) return;
      setState(
        () => _error = error is ApiException
            ? error.message
            : 'Не удалось продолжить. Попробуйте ещё раз.',
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    await _action(() async {
      final session = widget.session;
      final email = _email.text.trim();
      switch (_step) {
        case _AuthStep.login:
        case _AuthStep.register:
          final register = _step == _AuthStep.register;
          final signedIn = await session.authenticate({
            'email': email,
            'password': _password.text,
            if (register) 'name': _name.text.trim(),
            if (register) 'password_confirm': _confirmation.text,
          }, register: register);
          if (!mounted) return;
          if (signedIn) {
            TextInput.finishAutofillContext(shouldSave: true);
            Navigator.of(context).pop(true);
          } else {
            _switchTo(_AuthStep.verify);
          }
        case _AuthStep.verify:
          await session.verifyEmail(_code.text.trim());
          if (mounted && session.signedIn) Navigator.of(context).pop(true);
        case _AuthStep.resetEmail:
          await session.api.post('/api/auth/password/reset/request', {
            'email': email,
          });
          if (mounted) {
            _switchTo(
              _AuthStep.resetCode,
              notice: 'Если аккаунт найден, мы отправили код на $email.',
            );
          }
        case _AuthStep.resetCode:
          await session.api.post('/api/auth/password/reset/confirm', {
            'email': email,
            'code': _code.text.trim(),
            'password': _password.text,
            'password_confirm': _confirmation.text,
          });
          if (mounted) {
            _switchTo(
              _AuthStep.login,
              notice: 'Пароль обновлён. Войдите с новым паролем.',
            );
          }
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final registering = _step == _AuthStep.register;
    final login = _step == _AuthStep.login;
    final verifying = _step == _AuthStep.verify;
    final resetEmail = _step == _AuthStep.resetEmail;
    final resetCode = _step == _AuthStep.resetCode;
    final (title, subtitle, submitLabel) = switch (_step) {
      _AuthStep.login => (
        'Вход',
        'Войдите с email, который используете в H-Point.',
        'Войти',
      ),
      _AuthStep.register => (
        'Регистрация',
        'Создайте аккаунт, чтобы публиковать заявки и общаться.',
        'Получить код',
      ),
      _AuthStep.verify => (
        'Подтвердите email',
        'Введите код из письма на ${_email.text.trim()}.',
        'Подтвердить',
      ),
      _AuthStep.resetEmail => (
        'Восстановление пароля',
        'Укажите email вашего аккаунта.',
        'Отправить код',
      ),
      _AuthStep.resetCode => (
        'Новый пароль',
        'Введите код из письма и придумайте пароль.',
        'Сохранить пароль',
      ),
    };
    return Scaffold(
      appBar: AppBar(title: const Text('H-Point')),
      body: SafeArea(
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 500),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
              children: [
                Text(title, style: theme.textTheme.headlineMedium),
                const SizedBox(height: 8),
                Text(
                  subtitle,
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 24),
                AutofillGroup(
                  key: ValueKey(_step),
                  onDisposeAction: AutofillContextAction.cancel,
                  child: Form(
                    key: _form,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (registering) ...[
                          TextFormField(
                            controller: _name,
                            enabled: !_busy,
                            textCapitalization: TextCapitalization.words,
                            textInputAction: TextInputAction.next,
                            autofillHints: const [AutofillHints.name],
                            decoration: const InputDecoration(labelText: 'Имя'),
                            maxLength: 50,
                            validator: (value) =>
                                (value ?? '').trim().length < 2
                                ? 'Укажите имя'
                                : null,
                          ),
                          const SizedBox(height: 8),
                        ],
                        if (login || registering || resetEmail) ...[
                          TextFormField(
                            controller: _email,
                            enabled: !_busy,
                            keyboardType: TextInputType.emailAddress,
                            textInputAction: resetEmail
                                ? TextInputAction.done
                                : TextInputAction.next,
                            autocorrect: false,
                            autofillHints: const [AutofillHints.email],
                            decoration: const InputDecoration(
                              labelText: 'Email',
                            ),
                            validator: (value) =>
                                RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
                                    .hasMatch((value ?? '').trim())
                                ? null
                                : 'Проверьте email',
                            onFieldSubmitted: resetEmail
                                ? (_) => _submit()
                                : null,
                          ),
                          const SizedBox(height: 12),
                        ],
                        if (verifying || resetCode) ...[
                          TextFormField(
                            controller: _code,
                            enabled: !_busy,
                            maxLength: 6,
                            keyboardType: TextInputType.number,
                            textInputAction: verifying
                                ? TextInputAction.done
                                : TextInputAction.next,
                            inputFormatters: [
                              FilteringTextInputFormatter.digitsOnly,
                            ],
                            autofillHints: const [AutofillHints.oneTimeCode],
                            decoration: const InputDecoration(
                              labelText: 'Код из письма',
                            ),
                            validator: (value) => value?.length == 6
                                ? null
                                : 'Введите шесть цифр',
                            onFieldSubmitted: verifying
                                ? (_) => _submit()
                                : null,
                          ),
                          const SizedBox(height: 8),
                        ],
                        if (login || registering || resetCode) ...[
                          TextFormField(
                            controller: _password,
                            enabled: !_busy,
                            obscureText: _obscure,
                            autocorrect: false,
                            enableSuggestions: false,
                            autofillHints: [
                              login
                                  ? AutofillHints.password
                                  : AutofillHints.newPassword,
                            ],
                            textInputAction: login
                                ? TextInputAction.done
                                : TextInputAction.next,
                            onFieldSubmitted: login ? (_) => _submit() : null,
                            decoration: InputDecoration(
                              labelText: 'Пароль',
                              suffixIcon: IconButton(
                                tooltip: _obscure
                                    ? 'Показать пароль'
                                    : 'Скрыть пароль',
                                icon: Icon(
                                  _obscure
                                      ? Icons.visibility_outlined
                                      : Icons.visibility_off_outlined,
                                ),
                                onPressed: () =>
                                    setState(() => _obscure = !_obscure),
                              ),
                            ),
                            validator: (value) =>
                                (value ?? '').isEmpty ? 'Введите пароль' : null,
                          ),
                          const SizedBox(height: 12),
                        ],
                        if (registering || resetCode) ...[
                          TextFormField(
                            controller: _confirmation,
                            enabled: !_busy,
                            obscureText: _obscure,
                            autocorrect: false,
                            enableSuggestions: false,
                            textInputAction: TextInputAction.done,
                            decoration: const InputDecoration(
                              labelText: 'Повторите пароль',
                            ),
                            validator: (value) => value == _password.text
                                ? null
                                : 'Пароли не совпадают',
                            onFieldSubmitted: (_) => _submit(),
                          ),
                          const SizedBox(height: 12),
                        ],
                        if (_error != null) ...[
                          Text(_error!, style: TextStyle(color: colors.error)),
                          const SizedBox(height: 12),
                        ],
                        if (_notice != null) ...[
                          Text(
                            _notice!,
                            style: TextStyle(color: colors.primary),
                          ),
                          const SizedBox(height: 12),
                        ],
                        FilledButton(
                          onPressed: _busy ? null : _submit,
                          child: _busy
                              ? const SizedBox.square(
                                  dimension: 20,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : Text(submitLabel),
                        ),
                        if (login)
                          TextButton(
                            onPressed: _busy
                                ? null
                                : () => _switchTo(_AuthStep.resetEmail),
                            child: const Text('Забыли пароль?'),
                          ),
                        if (verifying)
                          TextButton(
                            onPressed: _busy
                                ? null
                                : () => _action(() async {
                                    await widget.session.api.post(
                                      '/api/auth/email/resend',
                                    );
                                    if (mounted) {
                                      setState(
                                        () => _notice = 'Новый код отправлен.',
                                      );
                                    }
                                  }),
                            child: const Text('Отправить код ещё раз'),
                          ),
                        TextButton(
                          onPressed: _busy
                              ? null
                              : () => _switchTo(
                                  login ? _AuthStep.register : _AuthStep.login,
                                ),
                          child: Text(
                            login ? 'Создать аккаунт' : 'Вернуться ко входу',
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
