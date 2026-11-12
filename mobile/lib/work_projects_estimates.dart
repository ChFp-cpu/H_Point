part of 'work_projects.dart';

const _estimateKinds = {
  'work': 'Работы',
  'material': 'Материалы',
  'other': 'Прочее',
};

class _EstimateCard extends StatefulWidget {
  const _EstimateCard({required this.model, required this.row, this.onEdit});

  final WorkModel model;
  final Json row;
  final VoidCallback? onEdit;

  @override
  State<_EstimateCard> createState() => _EstimateCardState();
}

class _EstimateCardState extends State<_EstimateCard> {
  bool _busy = false;

  Future<void> _action(String action) async {
    if (_busy) return;
    final model = widget.model;
    final id = widget.row['id'];
    final owner = model.ownerId;
    final account = model.session.data?['current_user_id'];
    if (id is! int || owner == null) return;
    if (action == 'delete') {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Удалить смету?'),
          content: Text(string(widget.row['title'])),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Удалить'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    if (!mounted ||
        model.ownerId != owner ||
        model.session.data?['current_user_id'] != account) {
      return;
    }
    setState(() => _busy = true);
    try {
      if (action.startsWith('export:')) {
        final parts = action.split(':');
        final format = parts[1];
        final audience = parts[2];
        final title = String.fromCharCodes(
          string(widget.row['title'], 'Смета').runes.take(70),
        );
        final suffix = audience == 'internal' ? '-внутренняя' : '';
        await model.shareExport(
          '/api/commercial/estimates/export',
          {
            'id': '$id',
            'owner_id': '$owner',
            'format': format,
            'audience': audience,
          },
          fileName: 'Смета-$title$suffix.$format',
          mimeType: format == 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        );
        return;
      }
      if (!_mayEdit(model, manage: true)) return;
      final changingStatus = action.startsWith('status:');
      await model.update(
        '/api/commercial/estimates/${changingStatus ? 'status' : action}',
        {
          'id': id,
          'owner_id': owner,
          if (changingStatus) 'status': action.substring('status:'.length),
          if (action == 'delete') 'confirm': true,
        },
      );
      if (mounted) {
        _notice(
          context,
          changingStatus
              ? 'Статус обновлён'
              : (action == 'delete' ? 'Смета удалена' : 'Черновик скопирован'),
        );
      }
    } catch (error) {
      if (mounted) _notice(context, '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final row = widget.row;
    final data = widget.model.data;
    final manager = object(data['permissions'])['manage'] == true;
    final editable = widget.onEdit != null;
    final status = string(row['status']);
    final objectTitle = _nameIn(
      rows(data['objects']),
      row['object_id'],
      'title',
    );
    final client = _nameIn(rows(data['clients']), row['client_id'], 'name');
    final number = string(row['number']);
    final validUntil = _dayLabel(context, row['valid_until']);
    final issued = _dayLabel(context, row['issued_on']);
    final notes = string(row['notes']);
    final lines = rows(row['items']);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 12, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: _WorkRecordHeader(
                    title: string(row['title'], 'Смета'),
                    status: _estimateStatuses[status] ?? status,
                  ),
                ),
                PopupMenuButton<String>(
                  enabled: !_busy,
                  tooltip: 'Действия со сметой',
                  onSelected: _action,
                  itemBuilder: (_) => [
                    if (editable) ...[
                      for (final entry in _estimateStatuses.entries)
                        if (entry.key != status)
                          PopupMenuItem(
                            value: 'status:${entry.key}',
                            child: Text('Статус · ${entry.value}'),
                          ),
                      const PopupMenuDivider(),
                      const PopupMenuItem(
                        value: 'duplicate',
                        child: Text('Копировать в черновик'),
                      ),
                      const PopupMenuItem(
                        value: 'delete',
                        child: Text('Удалить смету'),
                      ),
                    ],
                    if (manager) ...[
                      const PopupMenuItem(
                        value: 'export:pdf:internal',
                        child: Text('Внутренняя смета · PDF'),
                      ),
                      const PopupMenuItem(
                        value: 'export:xlsx:internal',
                        child: Text('Внутренняя смета · Excel'),
                      ),
                    ],
                    const PopupMenuItem(
                      value: 'export:pdf:client',
                      child: Text('Смета для клиента · PDF'),
                    ),
                    const PopupMenuItem(
                      value: 'export:xlsx:client',
                      child: Text('Смета для клиента · Excel'),
                    ),
                  ],
                ),
              ],
            ),
            if (number.isNotEmpty) _WorkRecordLine(Icons.tag_outlined, number),
            if (objectTitle.isNotEmpty)
              _WorkRecordLine(Icons.location_city_outlined, objectTitle),
            if (client.isNotEmpty)
              _WorkRecordLine(Icons.person_outline, client),
            if (issued.isNotEmpty || validUntil.isNotEmpty)
              _WorkRecordLine(
                Icons.event_outlined,
                [
                  if (issued.isNotEmpty) 'от $issued',
                  if (validUntil.isNotEmpty) 'действует до $validUntil',
                ].join(' · '),
              ),
            const SizedBox(height: 8),
            Text(
              _money(row['total_rub']),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 10),
              shape: const Border(),
              collapsedShape: const Border(),
              title: const Text('Состав сметы'),
              subtitle: Text('Позиций: ${lines.length}'),
              expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final line in lines)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          string(line['title'], 'Позиция'),
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        Text(
                          '${_estimateKinds[line['kind']] ?? 'Работы'} · '
                          '${_value(line['quantity']).replaceAll('.', ',')} ${string(line['unit'], 'шт.')} × ${_money(line['price_rub'])} = ${_money(line['total_rub'])}',
                        ),
                      ],
                    ),
                  ),
                _EstimateTotals(quote: row),
                if (notes.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(notes),
                  ),
              ],
            ),
            if (editable)
              TextButton.icon(
                onPressed: _busy ? null : widget.onEdit,
                icon: const Icon(Icons.edit_outlined),
                label: const Text('Изменить'),
              ),
          ],
        ),
      ),
    );
  }
}

class _EstimateLine {
  _EstimateLine([Json row = const {}])
    : kind = _estimateKinds.containsKey(row['kind'])
          ? row['kind'] as String
          : 'work',
      title = TextEditingController(text: string(row['title'])),
      unit = TextEditingController(text: string(row['unit'], 'шт.')),
      quantity = TextEditingController(
        text: _value(row['quantity'], '1').replaceAll('.', ','),
      ),
      price = TextEditingController(
        text: _value(row['price_rub']).replaceAll('.', ','),
      ),
      cost = TextEditingController(
        text: _value(row['cost_rub']).replaceAll('.', ','),
      );

  String kind;
  final TextEditingController title, unit, quantity, price, cost;

  Json get payload => {
    'kind': kind,
    'title': title.text.trim(),
    'unit': unit.text.trim(),
    'quantity': quantity.text.trim(),
    'price_rub': _amount(price),
    'cost_rub': _amount(cost),
  };

  void dispose() {
    for (final controller in [title, unit, quantity, price, cost]) {
      controller.dispose();
    }
  }
}

String _amount(TextEditingController controller) =>
    controller.text.trim().isEmpty ? '0' : controller.text.trim();

class _EstimateEditor extends StatefulWidget {
  const _EstimateEditor({required this.model, this.record});

  final WorkModel model;
  final Json? record;

  @override
  State<_EstimateEditor> createState() => _EstimateEditorState();
}

class _EstimateEditorState extends State<_EstimateEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _title, _number, _notes, _markup, _discount;
  late final List<_EstimateLine> _lines;
  late final int? _ownerId;
  late final Object? _accountId;
  late int _object, _client;
  late String _status;
  DateTime? _issued, _validUntil;
  Json? _quote;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final row = widget.record ?? {};
    _ownerId = widget.model.ownerId;
    _accountId = widget.model.session.data?['current_user_id'];
    _title = TextEditingController(text: string(row['title']));
    _number = TextEditingController(text: string(row['number']));
    _notes = TextEditingController(text: string(row['notes']));
    _markup = TextEditingController(
      text: _value(row['markup_percent']).replaceAll('.', ','),
    );
    _discount = TextEditingController(
      text: _value(row['discount_percent']).replaceAll('.', ','),
    );
    _lines = rows(row['items']).map(_EstimateLine.new).toList();
    if (_lines.isEmpty) _lines.add(_EstimateLine());
    _object = row['object_id'] as int? ?? 0;
    _client = row['client_id'] as int? ?? 0;
    final status = string(row['status']);
    _status = _estimateStatuses.containsKey(status) ? status : 'draft';
    _issued = DateTime.tryParse(_value(row['issued_on']));
    _validUntil = DateTime.tryParse(_value(row['valid_until']));
    _quote = widget.record;
  }

  @override
  void dispose() {
    for (final controller in [_title, _number, _notes, _markup, _discount]) {
      controller.dispose();
    }
    for (final line in _lines) {
      line.dispose();
    }
    super.dispose();
  }

  void _clearQuote() {
    if (_quote != null || _error != null) {
      setState(() {
        _quote = null;
        _error = null;
      });
    }
  }

  Future<void> _submit({bool save = false}) async {
    if (_busy || !_validateWorkForm(_form)) return;
    final model = widget.model;
    if (_ownerId == null ||
        _ownerId != model.ownerId ||
        _accountId != model.session.data?['current_user_id'] ||
        !_mayEdit(model, manage: true)) {
      setState(() => _error = 'Кабинет изменился. Откройте форму заново.');
      return;
    }
    if (save &&
        _issued != null &&
        _validUntil != null &&
        _validUntil!.isBefore(_issued!)) {
      setState(
        () => _error = 'Срок действия должен быть не раньше даты составления.',
      );
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    final amounts = {
      'owner_id': _ownerId,
      'items': _lines.map((line) => line.payload).toList(),
      'markup_percent': _amount(_markup),
      'discount_percent': _amount(_discount),
    };
    try {
      if (save) {
        await model.update('/api/commercial/estimates', {
          ...amounts,
          if (widget.record != null) 'id': widget.record!['id'],
          'title': _title.text.trim(),
          'number': _number.text.trim(),
          'object_id': _object == 0 ? null : _object,
          'client_id': _client == 0 ? null : _client,
          'status': _status,
          'issued_on': _dayPayload(_issued),
          'valid_until': _dayPayload(_validUntil),
          'notes': _notes.text.trim(),
        });
        if (mounted) Navigator.of(context).pop(true);
      } else {
        final response = await model.api.post(
          '/api/commercial/estimates/quote',
          amounts,
        );
        final quote = object(object(response['result'])['quote']);
        if (quote.isEmpty) {
          throw const FormatException('Не удалось получить итог сметы.');
        }
        if (mounted) setState(() => _quote = quote);
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _decimal(
    String label,
    TextEditingController controller,
    int max, {
    bool positive = false,
    String? suffix,
  }) => TextFormField(
    controller: controller,
    enabled: !_busy,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    textInputAction: TextInputAction.next,
    decoration: InputDecoration(labelText: label, suffixText: suffix),
    onChanged: (_) => _clearQuote(),
    validator: (value) {
      final input = (value ?? '').trim();
      if (input.isEmpty && !positive) return null;
      final amount = num.tryParse(input.replaceAll(',', '.'));
      if (!RegExp(r'^(?:\d+(?:[.,]\d{0,4})?|[.,]\d{1,4})$').hasMatch(input) ||
          amount == null ||
          amount > max ||
          (positive && amount <= 0)) {
        return 'Введите ${positive ? 'число больше 0' : 'число'} до $max';
      }
      return null;
    },
  );

  Widget _line(_EstimateLine line, int index) => Card(
    key: ObjectKey(line),
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Позиция ${index + 1}',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              IconButton(
                tooltip: 'Удалить позицию',
                onPressed: _busy || _lines.length == 1
                    ? null
                    : () {
                        setState(() {
                          _lines.removeAt(index);
                          _quote = null;
                        });
                        WidgetsBinding.instance.addPostFrameCallback(
                          (_) => line.dispose(),
                        );
                      },
                icon: const Icon(Icons.delete_outline),
              ),
            ],
          ),
          _WorkSelect<String>(
            label: 'Группа',
            value: line.kind,
            choices: _estimateKinds,
            onChanged: _busy
                ? null
                : (value) => setState(() {
                    line.kind = value;
                    _quote = null;
                  }),
          ),
          const SizedBox(height: 10),
          TextFormField(
            controller: line.title,
            enabled: !_busy,
            maxLength: 160,
            decoration: const InputDecoration(
              labelText: 'Наименование',
              counterText: '',
            ),
            textInputAction: TextInputAction.next,
            onChanged: (_) => _clearQuote(),
            validator: (value) => (value ?? '').trim().isEmpty
                ? 'Укажите наименование позиции'
                : null,
          ),
          const SizedBox(height: 10),
          TextFormField(
            controller: line.unit,
            enabled: !_busy,
            maxLength: 24,
            decoration: const InputDecoration(
              labelText: 'Единица измерения',
              counterText: '',
            ),
            textInputAction: TextInputAction.next,
            onChanged: (_) => _clearQuote(),
          ),
          const SizedBox(height: 10),
          _decimal('Количество', line.quantity, 1000000, positive: true),
          const SizedBox(height: 10),
          _decimal('Цена за единицу', line.price, 100000000, suffix: 'тест. ₽'),
          const SizedBox(height: 10),
          _decimal(
            'Себестоимость за единицу',
            line.cost,
            100000000,
            suffix: 'тест. ₽',
          ),
        ],
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final data = widget.model.data;
    return _WorkEditorFrame(
      title: widget.record == null ? 'Новая смета' : 'Редактирование сметы',
      form: _form,
      busy: _busy,
      error: _error,
      onSave: () => _submit(save: true),
      fields: [
        TextFormField(
          controller: _title,
          enabled: !_busy,
          maxLength: 160,
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            labelText: 'Название сметы',
            counterText: '',
          ),
          validator: (value) =>
              (value ?? '').trim().isEmpty ? 'Введите название' : null,
        ),
        TextFormField(
          controller: _number,
          enabled: !_busy,
          maxLength: 40,
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            labelText: 'Номер документа',
            counterText: '',
          ),
        ),
        _WorkSelect<String>(
          label: 'Статус',
          value: _status,
          choices: _estimateStatuses,
          onChanged: _busy ? null : (value) => setState(() => _status = value),
        ),
        _WorkSelect<int>(
          label: 'Объект',
          value: _object,
          choices: _recordChoices(
            rows(data['objects']),
            label: 'title',
            empty: 'Без объекта',
            current: _object,
          ),
          onChanged: _busy ? null : (value) => setState(() => _object = value),
        ),
        _WorkSelect<int>(
          label: 'Клиент',
          value: _client,
          choices: _recordChoices(
            rows(data['clients']),
            label: 'name',
            empty: 'Без клиента',
            current: _client,
          ),
          onChanged: _busy ? null : (value) => setState(() => _client = value),
        ),
        _WorkDate(
          label: 'Дата составления',
          value: _issued,
          onChanged: _busy ? null : (value) => setState(() => _issued = value),
        ),
        _WorkDate(
          label: 'Действует до',
          value: _validUntil,
          onChanged: _busy
              ? null
              : (value) => setState(() => _validUntil = value),
        ),
        Text('Позиции сметы', style: Theme.of(context).textTheme.titleMedium),
        for (final (index, line) in _lines.indexed) _line(line, index),
        OutlinedButton.icon(
          onPressed: _busy || _lines.length >= 100
              ? null
              : () => setState(() {
                  _lines.add(_EstimateLine());
                  _quote = null;
                }),
          icon: const Icon(Icons.add),
          label: const Text('Добавить позицию'),
        ),
        _decimal('Наценка', _markup, 1000, suffix: '%'),
        _decimal('Скидка', _discount, 100, suffix: '%'),
        TextFormField(
          controller: _notes,
          enabled: !_busy,
          minLines: 2,
          maxLines: 5,
          maxLength: 4000,
          decoration: const InputDecoration(
            labelText: 'Примечание',
            alignLabelWithHint: true,
            counterText: '',
          ),
        ),
        FilledButton.tonalIcon(
          onPressed: _busy ? null : () => _submit(),
          icon: const Icon(Icons.calculate_outlined),
          label: const Text('Рассчитать итог'),
        ),
        if (_quote != null) _EstimateTotals(quote: _quote!),
      ],
    );
  }
}

class _EstimateTotals extends StatelessWidget {
  const _EstimateTotals({required this.quote});

  final Json quote;

  @override
  Widget build(BuildContext context) {
    final breakdown = {
      'По позициям': 'subtotal_rub',
      'Наценка': 'markup_rub',
      'Скидка': 'discount_rub',
      'Итого': 'total_rub',
      'Себестоимость': 'cost_rub',
      'Прибыль': 'profit_rub',
    };
    return Card(
      margin: EdgeInsets.zero,
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final entry in breakdown.entries)
              if (quote.containsKey(entry.value))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Wrap(
                    alignment: WrapAlignment.spaceBetween,
                    spacing: 8,
                    children: [
                      Text(entry.key),
                      Text(
                        _money(quote[entry.value]),
                        style: entry.value == 'total_rub'
                            ? const TextStyle(fontWeight: FontWeight.w700)
                            : null,
                      ),
                    ],
                  ),
                ),
          ],
        ),
      ),
    );
  }
}
