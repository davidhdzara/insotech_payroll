# -*- coding: utf-8 -*-
"""E-9 (H-QA-026): el Salario es MENSUAL en Colombia (``CO_BASICO = wage / 30``), sin importar «Programar pago»; cargar $6.000.000 pensando que es por quincena pagaba $3.000.000
por quincena.

v19 (H-V19-14, bloque 2; opción B del TL): no hay rótulos nativos de período junto al salario — el rótulo ES el selector ``schedule_pay``, que ``hr_payroll`` pone en la misma
fila (``enterprise/hr_payroll/views/hr_employee_views.xml:51-54``). El selector se conserva intacto y, solo para compañías colombianas, se agrega junto al salario el texto fijo
«El valor es mensual», sin clases ni estilos propios. (En v18 se ocultaban los 9 rótulos nativos y quedaba solo «/ mes».)

Un ``arch`` de vista no se ve con el navegador en una prueba de servidor: se evalúan las condiciones ``invisible`` del ``arch`` EFECTIVO (con la herencia ya aplicada), que es lo
mismo que evalúa el cliente."""

from lxml import etree

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

NOMBRE_TEXTO_CO = 'l10n_co_ne_wage_period_label'
TEXTO_CO = 'El valor es mensual'
VISTAS_PROPIAS = ('view_employee_form_ne', 'view_employee_form_ne_contrato', 'view_employee_form_ne_salario_mes',
                  'view_employee_form_ne_deducciones', 'view_employee_form_ne_retefuente')


@tagged('post_install', '-at_install')
class TestSalarioMes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        vista = cls.env.ref('hr.view_employee_form')
        cls.arch = etree.fromstring(cls.env['hr.employee'].get_view(vista.id, 'form')['arch'].encode())
        campo = cls.env['hr.employee']._fields['schedule_pay']
        cls.valores_schedule_pay = [valor for valor, _etiqueta in campo.get_description(cls.env)['selection']]

    def _fila_del_salario(self):
        fila = self.arch.xpath("//page[@name='payroll_information']//div[@name='wage']")
        self.assertEqual(len(fila), 1, 'La fila del salario ya no está en la pestaña Nómina de la ficha.')
        return fila[0]

    def _texto_co(self):
        texto = self._fila_del_salario().xpath("./span[@name='%s']" % NOMBRE_TEXTO_CO)
        self.assertEqual(len(texto), 1)
        return texto[0]

    def _selector(self):
        selector = self._fila_del_salario().xpath("./field[@name='schedule_pay']")
        self.assertEqual(len(selector), 1, 'El selector nativo de Programar pago ya no está en la fila del salario.')
        return selector[0]

    def _visible(self, nodo, schedule_pay, pais):
        condicion = nodo.get('invisible')
        return not (condicion and safe_eval(condicion, {'schedule_pay': schedule_pay, 'company_country_code': pais}))

    def test_la_vista_del_contrato_carga_con_el_rotulo_colombiano(self):
        texto = self._texto_co()
        self.assertEqual(''.join(texto.itertext()).strip(), TEXTO_CO)
        self.assertEqual(set(texto.attrib), {'name', 'invisible'}, 'Sin clases ni estilos propios')

    def test_el_selector_nativo_esta_una_vez_y_el_texto_colombiano_no_se_ve_en_mexico(self):
        """Control de la premisa: en v19 el período lo dice el selector nativo; fuera de Colombia nuestro texto no se ve con ningún valor."""
        self._selector()
        for valor in self.valores_schedule_pay:
            with self.subTest(schedule_pay=valor):
                self.assertFalse(self._visible(self._texto_co(), valor, 'MX'))

    def test_colombia_muestra_el_texto_mensual_con_cualquier_programar_pago(self):
        self.assertIn('semi-monthly', self.valores_schedule_pay)
        for valor in self.valores_schedule_pay:
            with self.subTest(schedule_pay=valor):
                self.assertTrue(self._visible(self._texto_co(), valor, 'CO'))
                self.assertTrue(self._visible(self._selector(), valor, 'CO'), 'El selector nativo sigue visible')

    def test_colombia_con_quincenal_muestra_el_texto_y_el_selector(self):
        """Premisa invertida respecto de v18 (opción B): el selector «Quincenal» se conserva; el texto aclara que el valor es mensual."""
        self.assertTrue(self._visible(self._texto_co(), 'semi-monthly', 'CO'))
        self.assertTrue(self._visible(self._selector(), 'semi-monthly', 'CO'))

    def test_otra_compania_conserva_el_comportamiento_nativo(self):
        for pais in ('MX', 'EC', False, ''):
            for valor in self.valores_schedule_pay:
                with self.subTest(pais=pais, schedule_pay=valor):
                    self.assertFalse(self._visible(self._texto_co(), valor, pais))
                    self.assertTrue(self._visible(self._selector(), valor, pais))

    def test_el_rotulo_nativo_mensual_sigue_para_otra_compania(self):
        """En otra compañía se ven el separador «/» y el selector nativos, sin nuestro texto."""
        separador = [s for s in self._fila_del_salario().xpath('./span') if (s.text or '').strip() == '/']
        self.assertEqual(len(separador), 1)
        self.assertTrue(self._visible(separador[0], 'monthly', 'MX'))
        self.assertTrue(self._visible(self._selector(), 'monthly', 'MX'))
        self.assertFalse(self._visible(self._texto_co(), 'monthly', 'MX'))

    def test_no_se_toca_programar_pago(self):
        """``schedule_pay`` (aviso de duración, factor de costos y la periodicidad de la retención lo leen) no se oculta ni se vuelve de solo lectura POR ESTE MÓDULO: ni
        nuestras vistas lo declaran o lo usan como destino de un xpath, ni la vista efectiva le pone condiciones."""
        for xmlid in VISTAS_PROPIAS:
            with self.subTest(vista=xmlid):
                propia = etree.fromstring(self.env.ref('l10n_co_nomina_electronica.%s' % xmlid).arch_db.encode())
                self.assertFalse(propia.xpath("//field[@name='schedule_pay']"), 'La vista propia declara schedule_pay.')
                for xpath in propia.xpath('//xpath'):
                    self.assertNotRegex(
                        xpath.get('expr'), r"""field\[@name\s*=\s*['"]schedule_pay['"]\]""",
                        'Un xpath propio apunta al campo schedule_pay.')
        selector = self._selector()
        for atributo in ('invisible', 'readonly', 'required'):
            self.assertFalse(selector.get(atributo), 'schedule_pay trae %s: %s.' % (atributo, selector.get(atributo)))

    def test_el_salario_conserva_su_campo_y_su_contenedor(self):
        """El campo ``wage`` sigue donde estaba, dentro de la fila del salario (solo se agrega el texto al lado)."""
        campo = self._fila_del_salario().xpath("./field[@name='wage']")
        self.assertEqual(len(campo), 1)
        self.assertNotIn('country', campo[0].get('invisible') or '')
