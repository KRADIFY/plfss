"""Arithmetic acceptance rules for independently sourced RAP amounts.

Never change a published amount. Since 23 September 2026, no discrepancy
above 10 EUR may pass automatically, including accumulated rounding.
Smaller discrepancies still require correct scope and complete extraction.
The older relative bound remains only where it is stricter than this cap.
"""

AUTOMATIC_DIFFERENCE_LIMIT_CENTS = 1000


def action_cents(item):
    value=item['cents'] if 'cents' in item else item['euros']*100
    assert type(value) is int,'An action amount must be integer cents'
    return value


def published_cents(group):
    value=group['published_total_cents'] if 'published_total_cents' in group else group['published_total_euros']*100
    assert type(value) is int,'A published total must be integer cents'
    return value


def capped_rounding_bound(rounded_terms=1, minimum_cents=100):
    return min(AUTOMATIC_DIFFERENCE_LIMIT_CENTS,
               max(minimum_cents, 50 * (rounded_terms + 1)))


def assess_difference(published_cents, reference_cents, rounded_terms=1):
    difference = published_cents - reference_cents
    rounding_limit = capped_rounding_bound(rounded_terms)
    materiality_limit = min(AUTOMATIC_DIFFERENCE_LIMIT_CENTS,
                            abs(reference_cents) // 1000)
    if difference == 0:
        status = 'exact'
    elif abs(difference) <= rounding_limit:
        status = 'published_rounding_difference'
    elif abs(difference) <= materiality_limit:
        status = 'source_difference'
    else:
        status = 'material_difference'
    return dict(status=status, difference_cents=difference,
                rounding_bound_cents=rounding_limit,
                materiality_bound_cents=materiality_limit,
                automatic_limit_cents=AUTOMATIC_DIFFERENCE_LIMIT_CENTS,
                review_required=status == 'material_difference',
                accepted=status != 'material_difference')


def difference_note(check):
    amount = f"{check['difference_cents']/100:+,.2f}".replace(',', ' ').replace('.', ',')
    if (abs(check['difference_cents']) > AUTOMATIC_DIFFERENCE_LIMIT_CENTS
            or check['status'] == 'material_difference'):
        return (f"Écart de {amount} € à analyser avant validation. "
                "La cause doit être établie ; aucune acceptation automatique "
                "d'un écart supérieur à 10 €. Les deux montants sont conservés.")
    if check['status'] == 'exact':
        return ''
    if check['status'] == 'published_rounding_difference':
        return f"Écart de précision de {amount} € avec le total de référence. Montants publiés conservés, sans répartition de l'écart."
    return (f"Écart de {amount} € avec le total de référence, dans la limite de 10 €. "
            "Le détail est celui du RAP ; le total de programme reste celui de la synthèse. "
            "Ce seuil ne démontre pas la cause de l'écart ni la complétude de l'extraction.")
