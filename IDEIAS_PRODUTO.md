# Ideias de produto — apoio ao fluxo da Bruna

> **Status: rascunho, nada aprovado.** Levantado em conversa em **2026-08-21**, depois do
> refactor encerrado. **Nada aqui vira código antes de conversar com a Bruna**, que volta
> de férias por volta de **2026-09-02**. A lista de perguntas no fim é o próximo passo,
> não a implementação.

## O dia dela, como foi descrito

| Etapa | Hoje | O sistema ajuda? |
|---|---|---|
| Busca no LinkedIn | Recruiter **Light**; download em lote limitado a **200 candidatos/mês**. O que passa disso ela abre perfil a perfil | não |
| Cadastro no nosso sistema | upload do PDF exportado | ✅ existe |
| Aderência + resumo | LLM diz se adere à vaga | ✅ existe |
| Contato com o candidato | ela escreve, um a um | não |
| Entrevista | normalmente **transcrita** | **não — o material fica fora do sistema** |
| Compliance | ela avalia | não |
| Envio ao gestor | e-mail; **às vezes monta um relatório a partir da transcrição** | **não — trabalho manual repetitivo** |

Ela **também cadastra o candidato no ATS da empresa**. Isso é a restrição de desenho mais
importante: **o nosso sistema não deve tentar virar ATS.** O valor dele é produzir **texto
pronto** que ela leva para o outro lado e para o gestor. O acompanhamento de estado já
existe aqui como uma flag que ela atualiza.

A licença pode mudar para o Recruiter completo, o que mexeria no teto de 200 — mas não
muda nada do que está abaixo.

## Escolhidos para fazer (depois de validar com ela)

1. **Roteiro de entrevista** gerado do currículo + vaga, dirigido às **lacunas** do perfil.
   Ela chega na call com a pauta pronta.
2. **Rascunho da mensagem de primeiro contato**, personalizada pelo currículo. Ela edita e
   manda — o texto sai como rascunho dela, nunca enviado pelo sistema.
3. **Entrada por texto colado**, além do PDF. Para os candidatos que passam do teto de 200
   e ela abre um a um, colar o perfil evita depender do export. Mesmo LLM, mesma extração.
4. **Checklist de compliance por vaga**, com estado — nada esquecido, e o gestor vê o que
   foi verificado.

Os três primeiros têm a mesma forma: uma chamada ao LLM que devolve texto para a tela. O
quarto é o único com modelo de dados novo.

## As apostas maiores, não escolhidas ainda

**A transcrição é o ativo parado mais valioso.** Ela já produz um material digital e rico,
e **já monta relatório dele à mão** para mandar por e-mail. Entrada digital, saída de
formato estável, público conhecido, repetição garantida. O efeito composto é o mais
interessante: o que a entrevista confirmou volta para o perfil e melhora a aderência dele
em **vagas futuras** — hoje o sistema só sabe o que estava no PDF do LinkedIn.

⚠️ **Se transcrição entrar, entra com política de retenção definida no primeiro dia** e com
registro do consentimento do candidato. É dado bem mais sensível que currículo, e o R-31
mostrou o custo de descobrir isso 719 arquivos depois.

**O teto de 200/mês diz que o banco de talentos vale mais que a importação.** O remédio não
é importar mais: é reaproveitar. Ao cadastrar uma vaga nova, ranquear **o banco inteiro**
contra ela antes de gastar download. Cada candidato passa a servir N vagas em vez de uma —
e o R-45 já mostrou que 32% do que entrava era repetição, ou seja, o acervo é maior do que
parece.

## O que não fazer

**Automatizar coleta no LinkedIn.** Viola os termos, arrisca a conta que é a ferramenta de
trabalho dela, e nem resolve — o gargalo é a licença, não o esforço de baixar.

**Duplicar o ATS da empresa.** Ela já cadastra lá. Funil paralelo aqui vira digitação em
dobro.

## O que perguntar a ela quando voltar (~02/09)

Estas são as perguntas cuja resposta **muda o desenho**, não perguntas de cortesia:

1. **Onde você perde mais tempo hoje?** — antes de qualquer lista nossa. A ordem dela vale
   mais que a nossa.
2. **O relatório que você manda para o gestor: dá para ver dois ou três reais?** O formato
   deles é a especificação pronta.
3. **De onde vem a transcrição** — Teams, Meet, alguma ferramenta? Isso define se é
   upload, colar texto ou integração.
4. **O que é "compliance"** no seu caso: documentos, referências, antecedentes, ou
   conformidade com requisitos da vaga? Quem cobra? O que acontece se falhar?
5. **A mensagem de primeiro contato**: você tem um modelo que reaproveita, ou escreve do
   zero toda vez? O que muda de candidato para candidato?
6. **Quando você abre perfil a perfil** (acima dos 200): o que exatamente você copia hoje?
7. **O que o LLM erra** com mais frequência no resumo e na aderência? Isso vale mais que
   feature nova.
8. **O que você faz fora do sistema** — planilha, bloco de notas, WhatsApp? É onde estão os
   buracos que a gente não enxerga daqui.

## Restrições que valem para qualquer uma delas

- **Memória:** a instância tem 416 MiB (R-49). Transcrição é texto longo dentro de um
  worker; qualquer feature que carregue muito texto reforça a necessidade de subir o plano.
- **Custo:** toda feature nova aqui é chamada de LLM paga. Estimar tokens por chamada e
  chamadas por dia **antes** de implementar.
- **Falha do LLM:** o R-43 nasceu de resposta vazia passando como sucesso, e um candidato
  se perdeu em silêncio. Toda chamada nova precisa de política explícita de vazio, timeout
  e retry.
- **A caixa que conta é a tela.** Cinco vezes neste projeto uma suíte verde não pegou o que
  uma tarde de uso real pegou.
