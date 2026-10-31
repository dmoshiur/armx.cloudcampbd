import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../core/widgets/primitives.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.apiBase, required this.onNeedsSignup});

  final String apiBase;
  final VoidCallback onNeedsSignup;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  bool _signup = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final auth = context.read<AuthController>();
    final ok = _signup
        ? await auth.signup(_email.text.trim(), _password.text, _name.text.trim())
        : await auth.login(_email.text.trim(), _password.text);
    if (!mounted) return;
    if (!ok && auth.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(auth.error!)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final size = MediaQuery.sizeOf(context);

    final form = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(_signup ? 'Create your account' : 'Sign in', style: Theme.of(context).textTheme.headlineLarge),
        const SizedBox(height: 6),
        Text(
          'New accounts start as a standard user. An administrator can grant the VIP role for device linking.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 20),
        if (_signup) ...[
          TextField(
            controller: _name,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Display name'),
          ),
          const SizedBox(height: 12),
        ],
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          autofillHints: const [AutofillHints.email],
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(labelText: 'Email'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _password,
          obscureText: true,
          autofillHints: const [AutofillHints.password],
          onSubmitted: (_) => _submit(),
          decoration: InputDecoration(
            labelText: 'Password',
            helperText: _signup ? 'At least 10 characters, one uppercase, one symbol' : null,
          ),
        ),
        const SizedBox(height: 20),
        ElevatedButton(
          onPressed: auth.busy ? null : _submit,
          child: auth.busy
              ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : Text(_signup ? 'Create account' : 'Sign in'),
        ),
        const SizedBox(height: 12),
        TextButton(
          onPressed: () => setState(() => _signup = !_signup),
          child: Text(_signup ? 'I already have an account' : 'Create an account'),
        ),
      ],
    );

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: ConstrainedBox(
              constraints: BoxConstraints(maxWidth: size.width >= ArmxTheme.contentMaxWidth ? 480 : 520),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            height: 36,
                            width: 36,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: ArmxColors.accent,
                              borderRadius: BorderRadius.circular(ArmxTheme.radiusMd),
                            ),
                            child: const Text('A', style: TextStyle(color: ArmxColors.ink, fontWeight: FontWeight.w800)),
                          ),
                          const SizedBox(width: 10),
                          Text('A.R.M.X AI', style: Theme.of(context).textTheme.titleMedium),
                        ],
                      ),
                      const SizedBox(height: 20),
                      form,
                      const SizedBox(height: 16),
                      Text(
                        'API: ${widget.apiBase}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
